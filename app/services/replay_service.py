from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from app.exceptions.domain import TaskNotFoundError
from app.repositories.task_repository import TaskRepository
from app.services.jsonl_service import IncrementalJsonlReader, SimulationDataProcessor


class ReplayService:
    _processors: ClassVar[dict[str, SimulationDataProcessor]] = {}

    def __init__(self, repo: TaskRepository) -> None:
        self._repo = repo

    async def _get_processor(self, task_id: str) -> SimulationDataProcessor:
        existing = self._processors.get(task_id)
        if existing is not None:
            existing.refresh()
            return existing

        task = await self._repo.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)

        output_dir = Path(task.output_dir or "")
        jsonl_candidates = [
            output_dir / "simulation_metrics.jsonl",
            output_dir / "metrics.jsonl",
        ]
        jsonl_path = next((path for path in jsonl_candidates if path.is_file()), jsonl_candidates[0])

        processor = SimulationDataProcessor(IncrementalJsonlReader(jsonl_path))
        processor.refresh()
        self._processors[task_id] = processor
        return processor

    async def get_metadata(self, task_id: str) -> dict[str, Any]:
        return (await self._get_processor(task_id)).get_metadata()

    async def get_snapshot(self, task_id: str, sim_time: int) -> dict[str, Any]:
        return (await self._get_processor(task_id)).get_all_hosts_snapshot(sim_time)

    async def get_timeline(
        self,
        task_id: str,
        start_time: int,
        end_time: int,
        interval_ms: int = 1000,
    ) -> dict[str, Any]:
        return (await self._get_processor(task_id)).get_timeline(start_time, end_time, interval_ms)

    async def get_summary(self, task_id: str) -> dict[str, Any]:
        return (await self._get_processor(task_id)).get_summary()

    async def get_latest_snapshot_time_at_or_before(
        self,
        task_id: str,
        sim_time: int,
    ) -> int | None:
        return (await self._get_processor(task_id)).get_latest_snapshot_time_at_or_before(sim_time)

    async def get_next_snapshot_time_after(
        self,
        task_id: str,
        sim_time: int,
    ) -> int | None:
        return (await self._get_processor(task_id)).get_next_snapshot_time_after(sim_time)

    async def get_host_history(
        self,
        task_id: str,
        host_id: str,
        start_time: int,
        end_time: int,
    ) -> dict[str, Any]:
        return (await self._get_processor(task_id)).get_host_history(host_id, start_time, end_time)

    async def get_vm_history(
        self,
        task_id: str,
        vm_id: str,
        start_time: int,
        end_time: int,
    ) -> dict[str, Any]:
        return (await self._get_processor(task_id)).get_vm_history(vm_id, start_time, end_time)

    async def get_call_chain(self, task_id: str, sim_time: int) -> dict[str, Any]:
        return (await self._get_processor(task_id)).get_call_chain_data(sim_time)
