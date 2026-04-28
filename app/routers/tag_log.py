"""Tag log from simulation metrics JSONL (algorithm_event + algorithm_name=stream_tag, details.tag_history)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.dependencies.services import get_replay_service
from app.schemas.simulation import ErrorResponse, ResourceLogEntry
from app.services.replay_service import ReplayService

router = APIRouter(tags=["replay"])


@router.get(
    "/tagLog",
    response_model=list[ResourceLogEntry],
    responses={404: {"model": ErrorResponse}},
)
async def get_tag_log(
    task_id: str = Query(..., description="Simulation task id"),
    sim_time: int = Query(..., description="Simulation time in milliseconds (inclusive upper bound by event t)"),
    replay: ReplayService = Depends(get_replay_service),
):
    """Expand details.tag_history into lines (流数据 id 的标签变为 …), t <= sim_time per step; up to 100 steps, oldest-first."""
    return await replay.get_tag_log(task_id, sim_time)
