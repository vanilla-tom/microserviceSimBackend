from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator

from app.models.task import TaskStatus
from app.repositories.task_repository import TaskRepository
from app.services.replay_service import ReplayService


class TaskStreamService:
    def __init__(self, repo: TaskRepository, replay: ReplayService) -> None:
        self._repo = repo
        self._replay = replay

    async def iter_messages(self, task_id: str) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        task = await self._repo.get_task(task_id)
        if task is None:
            yield "failed", {"error": "Task not found"}
            return

        last_streamed_sim_time: int | None = None
        sent_metadata = False

        while True:
            task = await self._repo.get_task(task_id)
            if task is None:
                yield "failed", {"error": "Task not found"}
                return

            yield "task_state", {
                "task_id": task.task_id,
                "status": task.status.value,
                "created_at": task.created_at,
                "start_time": task.start_time,
                "end_time": task.end_time,
                "real_start_time": task.real_start_time,
                "error_message": task.error_message,
            }

            try:
                metadata = await self._replay.get_metadata(task_id)
            except Exception:
                metadata = None

            if metadata is not None and not sent_metadata:
                yield "metadata", metadata
                sent_metadata = True

            if metadata is not None:
                sim_time_min = metadata.get("sim_time_min", 0)
                real_start_time = task.real_start_time or int(time.time() * 1000)
                now_ms = int(time.time() * 1000)
                aligned_now = sim_time_min + max(0, now_ms - real_start_time)

                if last_streamed_sim_time is None:
                    last_streamed_sim_time = await self._replay.get_latest_snapshot_time_at_or_before(
                        task_id,
                        aligned_now,
                    )

                    if last_streamed_sim_time is not None:
                        snapshot = await self._replay.get_snapshot(task_id, last_streamed_sim_time)
                        call_chain = await self._replay.get_call_chain(task_id, last_streamed_sim_time)
                        summary = await self._replay.get_summary(task_id)
                        yield "metrics_tick", {
                            "sim_time": last_streamed_sim_time,
                            "scheduled_real_time": real_start_time + max(0, last_streamed_sim_time - sim_time_min),
                            "is_live_edge": False,
                            "snapshot": snapshot,
                            "call_chain": call_chain,
                        }
                        yield "summary_update", summary

                next_snapshot_time = await self._replay.get_next_snapshot_time_after(
                    task_id,
                    last_streamed_sim_time if last_streamed_sim_time is not None else sim_time_min - 1,
                )

                if next_snapshot_time is not None:
                    scheduled_real_time = real_start_time + max(0, next_snapshot_time - sim_time_min)
                    delay_ms = scheduled_real_time - int(time.time() * 1000)
                    if delay_ms > 0:
                        yield "stream_status", {
                            "status": "ahead_of_schedule",
                            "scheduled_real_time": scheduled_real_time,
                            "delay_ms": delay_ms,
                        }
                        await asyncio.sleep(delay_ms / 1000)
                    snapshot = await self._replay.get_snapshot(task_id, next_snapshot_time)
                    call_chain = await self._replay.get_call_chain(task_id, next_snapshot_time)
                    summary = await self._replay.get_summary(task_id)
                    yield "metrics_tick", {
                        "sim_time": next_snapshot_time,
                        "scheduled_real_time": scheduled_real_time,
                        "is_live_edge": True,
                        "snapshot": snapshot,
                        "call_chain": call_chain,
                    }
                    yield "summary_update", summary
                    last_streamed_sim_time = next_snapshot_time
                else:
                    yield "stream_status", {
                        "status": "waiting_for_new_data",
                        "scheduled_real_time": real_start_time + max(0, aligned_now - sim_time_min),
                        "delay_ms": 0,
                    }

            if task.status == TaskStatus.COMPLETED:
                yield "complete", {"task_id": task.task_id}
                return

            if task.status == TaskStatus.FAILED:
                yield "failed", {
                    "task_id": task.task_id,
                    "error_message": task.error_message,
                }
                return

            await asyncio.sleep(1.0)
