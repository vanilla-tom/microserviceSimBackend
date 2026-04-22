from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence
from uuid import uuid4

from app.config import settings
from app.path_constants import TASK_LAUNCH_PARAMS_FILENAME
from app.exceptions.domain import (
    DefaultConfigNotFoundError,
    EmptyUploadedConfigError,
    InvalidResultFilenameError,
    NoResultFilesError,
    ResultFileNotFoundError,
    SimulationCreateFailedError,
    TaskNotFoundError,
    TaskNotReadyError,
)
from app.models.task import Task, TaskStatus
from app.repositories.task_repository import TaskRepository
from app.services import process_manager
from app.services.replay_service import ReplayService
from app.schemas.simulation import SimulationLaunchParams
from app.utils.file_helpers import (
    cleanup_task_directory,
    copy_default_config,
    find_result_files,
    patch_config_launch_overrides,
    patch_config_output_dir,
    save_launch_params,
    save_uploaded_config,
    setup_task_directory,
)


def _generate_task_id() -> str:
    return f"sim_{int(time.time())}_{uuid4().hex[:6]}"


def _workload_csv_filename(params: SimulationLaunchParams) -> str:
    suffix = "damaged" if params.enable_sensor_failure else "normal"
    return f"{params.scenario}_{params.data_source}_{suffix}.csv"


@dataclass(frozen=True)
class ResolvedResultFile:
    path: Path
    media_type: str
    filename: str


class SimulationService:
    def __init__(self, repo: TaskRepository) -> None:
        self._repo = repo

    async def create_simulation(
        self,
        launch_params: SimulationLaunchParams,
        config_upload: Optional[bytes] = None,
    ) -> str:
        task_id = _generate_task_id()
        try:
            config_path, output_dir = await setup_task_directory(
                settings.DATA_DIR, task_id
            )
            task_dir = output_dir.parent
            launch_params_path = task_dir / TASK_LAUNCH_PARAMS_FILENAME

            if config_upload is not None:
                if not config_upload:
                    raise EmptyUploadedConfigError
                await save_uploaded_config(config_upload, config_path)
            else:
                try:
                    await copy_default_config(settings.SIM_PROJECT_DIR, config_path)
                except FileNotFoundError as e:
                    raise DefaultConfigNotFoundError(str(e)) from e

            filename = _workload_csv_filename(launch_params)
            csv_path = settings.SOURCE_DATA_DIR / filename
            if not csv_path.is_file():
                raise DefaultConfigNotFoundError(
                    f"Workload CSV not found: {csv_path} (expected under SOURCE_DATA_DIR)"
                )

            await patch_config_output_dir(config_path, output_dir)
            await patch_config_launch_overrides(
                config_path,
                chaos_enable=launch_params.enable_node_failure,
                workload_csv_path=csv_path,
            )

            record: dict[str, Any] = {
                **launch_params.model_dump(mode="json", by_alias=True),
                "filename": filename,
                "resourcePath": csv_path.resolve().as_posix(),
            }
            await save_launch_params(record, launch_params_path)

            await self._repo.create_task(
                task_id=task_id,
                config_path=str(config_path.resolve()),
                output_dir=str(output_dir.resolve()),
            )

            await process_manager.launch_simulation(task_id)
            return task_id

        except (
            EmptyUploadedConfigError,
            DefaultConfigNotFoundError,
        ):
            cleanup_task_directory(settings.DATA_DIR, task_id)
            raise
        except FileNotFoundError as e:
            cleanup_task_directory(settings.DATA_DIR, task_id)
            raise DefaultConfigNotFoundError(str(e)) from e
        except Exception as e:
            cleanup_task_directory(settings.DATA_DIR, task_id)
            raise SimulationCreateFailedError(str(e)) from e

    async def list_tasks(
        self,
        *,
        status: Optional[TaskStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Task]:
        return await self._repo.list_tasks(
            status=status, limit=limit, offset=offset
        )

    async def get_task(self, task_id: str) -> Task:
        task = await self._repo.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        return task

    async def get_primary_result_file(self, task_id: str) -> ResolvedResultFile:
        task = await self.get_task(task_id)
        if task.status != TaskStatus.COMPLETED:
            raise TaskNotReadyError(task_id, task.status.value)

        output_dir = Path(task.output_dir or "")
        result_files = find_result_files(output_dir)

        if not result_files:
            raise NoResultFilesError(task_id)

        result_file = result_files[0]
        if result_file.suffix == ".jsonl":
            media_type = "application/x-ndjson"
        else:
            media_type = "text/csv"
        return ResolvedResultFile(
            path=result_file,
            media_type=media_type,
            filename=result_file.name,
        )

    async def list_result_filenames(self, task_id: str) -> list[str]:
        task = await self.get_task(task_id)
        if task.status != TaskStatus.COMPLETED:
            raise TaskNotReadyError(task_id, task.status.value)

        output_dir = Path(task.output_dir or "")
        result_files = find_result_files(output_dir)

        if not result_files:
            return []

        return [f.name for f in result_files]

    async def resolve_result_download(
        self, task_id: str, filename: str
    ) -> ResolvedResultFile:
        task = await self.get_task(task_id)
        if task.status != TaskStatus.COMPLETED:
            raise TaskNotReadyError(task_id, task.status.value)

        output_dir = Path(task.output_dir or "")
        file_path = output_dir / filename

        try:
            file_path.resolve().relative_to(output_dir.resolve())
        except ValueError as e:
            raise InvalidResultFilenameError("Invalid filename") from e

        if not file_path.is_file():
            raise ResultFileNotFoundError(filename)

        media_type = (
            "application/x-ndjson" if file_path.suffix == ".jsonl" else "text/csv"
        )
        return ResolvedResultFile(
            path=file_path,
            media_type=media_type,
            filename=filename,
        )

    async def cancel_and_delete(self, task_id: str) -> None:
        task = await self.get_task(task_id)

        if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            await process_manager.cancel_simulation(task_id)
            await self._repo.set_completed(task_id)

        cleanup_task_directory(settings.DATA_DIR, task_id)
        await self._repo.delete_task(task_id)
        ReplayService.evict_processor(task_id)

    async def cancel_task(self, task_id: str) -> Task:
        task = await self.get_task(task_id)
        if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            await process_manager.cancel_simulation(task_id)
            await self._repo.set_failed(task_id, "Cancelled by user")
        return await self.get_task(task_id)

    async def delete_task(self, task_id: str) -> None:
        await self.cancel_and_delete(task_id)

    async def get_launch_params(self, task_id: str) -> dict[str, Any]:
        task = await self.get_task(task_id)
        task_dir = Path(task.output_dir or "").parent
        launch_params_path = task_dir / TASK_LAUNCH_PARAMS_FILENAME
        if not launch_params_path.is_file():
            raise DefaultConfigNotFoundError(
                f"Launch params not found for task: {launch_params_path}"
            )
        return json.loads(launch_params_path.read_text(encoding="utf-8"))
