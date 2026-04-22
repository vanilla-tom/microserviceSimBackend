from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, List, Optional

import aiofiles

from app.path_constants import (
    METRICS_JSONL_FILENAMES,
    SIM_DEFAULT_CONFIG_RELATIVE_PATHS,
    TASK_CONFIG_FILENAME,
    TASK_OUTPUT_SUBDIR,
)


def _safe_task_dir(data_dir: Path, task_id: str) -> Path:
    base = data_dir.resolve()
    task_dir = (data_dir / task_id).resolve()
    try:
        task_dir.relative_to(base)
    except ValueError as e:
        raise ValueError(f"Invalid task_id: {task_id}") from e
    return task_dir


async def setup_task_directory(data_dir: Path, task_id: str) -> tuple[Path, Path]:
    """Create task directory structure. Returns (config_path, output_dir)."""
    task_dir = _safe_task_dir(data_dir, task_id)
    output_dir = task_dir / TASK_OUTPUT_SUBDIR
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path = task_dir / TASK_CONFIG_FILENAME
    return config_path, output_dir


async def save_uploaded_config(upload_content: bytes, dest_path: Path) -> None:
    """Save uploaded config file content to disk."""
    async with aiofiles.open(str(dest_path), "wb") as f:
        await f.write(upload_content)


async def copy_default_config(sim_project_dir: Path, dest_path: Path) -> None:
    """Copy default config from simulation project."""
    default_paths = [sim_project_dir / rel for rel in SIM_DEFAULT_CONFIG_RELATIVE_PATHS]
    for src in default_paths:
        if src.is_file():
            async with aiofiles.open(str(src), "rb") as sf:
                content = await sf.read()
            async with aiofiles.open(str(dest_path), "wb") as df:
                await df.write(content)
            return
    raise FileNotFoundError(
        f"Default config not found in {sim_project_dir}"
    )


async def patch_config_output_dir(config_path: Path, output_dir: Path) -> None:
    """Append metrics.outputDir override to config file.

    HOCON 'last-key-wins' semantics make appending safe without a parser.
    """
    abs_output = output_dir.resolve().as_posix()
    override_line = f'\nmetrics.outputDir = "{abs_output}"\n'
    async with aiofiles.open(str(config_path), "a", encoding="utf-8") as f:
        await f.write(override_line)


async def patch_config_launch_overrides(
    config_path: Path,
    *,
    chaos_enable: bool,
    workload_csv_path: Path,
) -> None:
    """Append chaos.enable and workload.csv.resourcePath (HOCON last-key-wins)."""
    abs_csv = workload_csv_path.resolve().as_posix()
    chaos_lit = str(chaos_enable).lower()
    block = (
        f"\nchaos.enable = {chaos_lit}\n"
        f'workload.csv.resourcePath = "{abs_csv}"\n'
    )
    async with aiofiles.open(str(config_path), "a", encoding="utf-8") as f:
        await f.write(block)


async def save_launch_params(record: dict[str, Any], dest_path: Path) -> None:
    async with aiofiles.open(str(dest_path), "w", encoding="utf-8") as f:
        await f.write(json.dumps(record, ensure_ascii=False, indent=2))


def cleanup_task_directory(data_dir: Path, task_id: str) -> None:
    """Remove the entire task directory."""
    try:
        task_dir = _safe_task_dir(data_dir, task_id)
    except ValueError:
        return
    if task_dir.exists():
        shutil.rmtree(task_dir, ignore_errors=True)


def find_result_files(output_dir: Path) -> Optional[List[Path]]:
    """Find result files in output directory.

    Checks for metrics.jsonl first (future), then falls back to CSV files.
    Returns list of result file paths or None.
    """
    if not output_dir.exists():
        return None

    # Prefer JSONL (future format)
    jsonl_candidates = [output_dir / name for name in METRICS_JSONL_FILENAMES]
    for jsonl in jsonl_candidates:
        if jsonl.is_file():
            return [jsonl]

    # Fallback: CSV files (current format)
    csv_files = sorted(output_dir.glob("*.csv"))
    if csv_files:
        return csv_files

    return None
