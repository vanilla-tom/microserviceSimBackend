"""Resource log from simulation metrics JSONL (algorithm_event + message_zh)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.dependencies.services import get_replay_service
from app.schemas.simulation import ErrorResponse, ResourceLogEntry
from app.services.replay_service import ReplayService

router = APIRouter(tags=["replay"])


@router.get(
    "/resourceLog",
    response_model=list[ResourceLogEntry],
    responses={404: {"model": ErrorResponse}},
)
async def get_resource_log(
    task_id: str = Query(..., description="Simulation task id"),
    sim_time: int = Query(..., description="Simulation time in milliseconds (inclusive upper bound by event t)"),
    replay: ReplayService = Depends(get_replay_service),
):
    """Return up to 100 algorithm_event lines with message_zh, with t <= sim_time, newest first then ascending by t."""
    return await replay.get_resource_log(task_id, sim_time)
