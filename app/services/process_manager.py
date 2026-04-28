from __future__ import annotations

import asyncio
import logging
import platform
import subprocess
from pathlib import Path
from typing import Dict

from app.config import settings
from app.repositories.task_repository import TaskRepository

_task_repo = TaskRepository()

logger = logging.getLogger(__name__)

# Active subprocesses keyed by task_id
_processes: Dict[str, asyncio.subprocess.Process] = {}
# Background asyncio tasks keyed by task_id
_tasks: Dict[str, asyncio.Task] = {}
# Concurrency limiter
_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_TASKS)
    return _semaphore


def _build_mvn_command(config_path: Path) -> list[str]:
    """Build the Maven command to launch the simulation."""
    jar_path = settings.SIM_PROJECT_DIR / "microservice-sim-1.0-SNAPSHOT-jar-with-dependencies.jar"
    return ["java", "-jar", str(jar_path.resolve()), "--config", str(config_path.resolve())]
    cmd = [settings.MVN_COMMAND]
    if settings.MVN_QUIET:
        cmd.append("-q")
    cmd.append("exec:java")

    abs_config = str(config_path.resolve())
    cmd.append(f'-Dexec.args=--config {abs_config}')
    return cmd


def _build_shell_command(config_path: Path) -> str:
    # """Build a single shell command string for Windows."""
    jar_path = settings.SIM_PROJECT_DIR / "microservice-sim-1.0-SNAPSHOT-jar-with-dependencies.jar"
    return f'java -jar "{jar_path.resolve()}" --config "{config_path.resolve()}"'
    parts = [settings.MVN_COMMAND]
    if settings.MVN_QUIET:
        parts.append("-q")
    parts.append("exec:java")

    abs_config = str(config_path.resolve())
    # On Windows cmd.exe, wrap the entire -D property in double quotes
    parts.append(f'"-Dexec.args=--config {abs_config}"')
    return " ".join(parts)


async def launch_simulation(task_id: str) -> None:
    """Schedule the simulation as a background asyncio task."""
    task = asyncio.create_task(_run_simulation(task_id))
    _tasks[task_id] = task
    task.add_done_callback(lambda _t: _tasks.pop(task_id, None))


async def _run_simulation(task_id: str) -> None:
    """Run the simulation subprocess and manage its lifecycle."""
    sem = _get_semaphore()

    try:
        # Wait for a concurrency slot
        await sem.acquire()

        db_task = await _task_repo.get_task(task_id)
        if db_task is None:
            logger.error("Task %s not found in DB, aborting launch", task_id)
            return

        config_path = Path(db_task.config_path)
        sim_dir = settings.SIM_PROJECT_DIR.resolve()

        if not sim_dir.is_dir():
            await _task_repo.set_failed(
                task_id, f"Simulation project directory not found: {sim_dir}"
            )
            return

        cmd = _build_mvn_command(config_path)

        # On Windows, mvn is a batch script, so we need shell=True
        is_windows = platform.system() == "Windows"

        if is_windows:
            shell_cmd = _build_shell_command(config_path)
            logger.info("Launching simulation %s: %s (cwd=%s)", task_id, shell_cmd, sim_dir)
            process = await asyncio.create_subprocess_shell(
                shell_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(sim_dir),
            )
        else:
            logger.info("Launching simulation %s: %s (cwd=%s)", task_id, cmd, sim_dir)
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(sim_dir),
            )

        _processes[task_id] = process

        # Mark as running
        await _task_repo.set_running(task_id, process.pid)

        # Wait for completion
        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            await _task_repo.set_completed(task_id)
            logger.info("Simulation %s completed successfully", task_id)
        else:
            # Prefer stderr for error messages, fall back to stdout
            err_text = stderr.decode("utf-8", errors="replace").strip() if stderr else ""
            out_text = stdout.decode("utf-8", errors="replace").strip() if stdout else ""
            error_msg = (err_text or out_text or "Unknown error (no output)")[:2000]
            await _task_repo.set_failed(task_id, error_msg)
            logger.error("Simulation %s failed (exit=%d): %s", task_id, process.returncode, error_msg[:200])

    except asyncio.CancelledError:
        logger.info("Simulation %s was cancelled", task_id)
        # Status is set by the caller (e.g. cancel API or shutdown_all both use set_completed).
        raise
    except Exception as e:
        logger.exception("Unexpected error running simulation %s", task_id)
        await _task_repo.set_failed(task_id, str(e)[:2000])
    finally:
        _processes.pop(task_id, None)
        sem.release()


async def cancel_simulation(task_id: str) -> bool:
    """Cancel a running simulation by killing the subprocess.

    Returns True if a process was found and killed.
    """
    process = _processes.get(task_id)
    bg_task = _tasks.get(task_id)

    killed = False

    if process is not None and process.returncode is None:
        try:
            if platform.system() == "Windows":
                # On Windows, use taskkill to kill the entire process tree
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                    capture_output=True,
                )
            else:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    process.kill()
            killed = True
        except ProcessLookupError:
            pass

    if bg_task is not None and not bg_task.done():
        bg_task.cancel()

    return killed


async def shutdown_all() -> None:
    """Gracefully stop all running simulations (called during app shutdown)."""
    task_ids = list(_processes.keys())
    for task_id in task_ids:
        await cancel_simulation(task_id)
        await _task_repo.set_completed(task_id)

    # Wait for background tasks to finish
    pending = [t for t in _tasks.values() if not t.done()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
