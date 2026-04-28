from __future__ import annotations

import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, ClassVar

from app.config import settings
from app.exceptions.domain import TaskNotFoundError
from app.models.task import Task
from app.path_constants import metrics_jsonl_paths
from app.repositories.task_repository import TaskRepository
from app.services.detector_service import (
    undamaged_detector_count_for_task,
    workload_peak_packets_per_second_for_task,
)
from app.services.jsonl_service import IncrementalJsonlReader, SimulationDataProcessor


class ReplayService:
    _processors: ClassVar[OrderedDict[str, SimulationDataProcessor]] = OrderedDict()
    _cache_lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, repo: TaskRepository) -> None:
        self._repo = repo

    @staticmethod
    def _cache_max_entries() -> int | None:
        n = settings.REPLAY_PROCESSOR_CACHE_MAX
        if n <= 0:
            return None
        return n

    @classmethod
    def evict_processor(cls, task_id: str) -> None:
        with cls._cache_lock:
            cls._processors.pop(task_id, None)

    @classmethod
    def clear_processors(cls) -> None:
        with cls._cache_lock:
            cls._processors.clear()

    @classmethod
    def _evict_lru_if_over_limit(cls) -> None:
        limit = cls._cache_max_entries()
        if limit is None:
            return
        while len(cls._processors) > limit:
            cls._processors.popitem(last=False)

    async def _get_processor(
        self,
        task_id: str,
        *,
        task: Task | None = None,
    ) -> SimulationDataProcessor:
        with self._cache_lock:
            existing = self._processors.get(task_id)
        if existing is not None:
            existing.refresh()
            with self._cache_lock:
                self._processors.move_to_end(task_id)
            return existing

        if task is None:
            task = await self._repo.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)

        output_dir = Path(task.output_dir or "")
        jsonl_candidates = list(metrics_jsonl_paths(output_dir))
        jsonl_path = next((path for path in jsonl_candidates if path.is_file()), jsonl_candidates[0])

        processor = SimulationDataProcessor(IncrementalJsonlReader(jsonl_path))
        processor.refresh()
        with self._cache_lock:
            self._processors[task_id] = processor
            self._processors.move_to_end(task_id)
            self._evict_lru_if_over_limit()
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
        task = await self._repo.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        summary = (await self._get_processor(task_id, task=task)).get_summary()
        summary["detector_count"] = undamaged_detector_count_for_task(task)
        summary["target_count_peak"] = workload_peak_packets_per_second_for_task(task)
        summary["interruption_count"] = 0
        return summary

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

    async def get_targets(self, task_id: str, sim_time: int) -> list[int]:
        return (await self._get_processor(task_id)).get_targets(sim_time)

    async def get_target_call_chain(
        self,
        task_id: str,
        sim_time: int,
        target_id: int,
    ) -> dict[str, Any]:
        return (await self._get_processor(task_id)).get_target_call_chain(sim_time, target_id)

    async def get_resource_log(self, task_id: str, sim_time: int) -> list[dict[str, Any]]:
        return (await self._get_processor(task_id)).get_algorithm_resource_messages(sim_time)

    async def get_tag_log(self, task_id: str, sim_time: int) -> list[dict[str, Any]]:
        return (await self._get_processor(task_id)).get_algorithm_tag_messages(sim_time)
