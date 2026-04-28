"""Simulation replay API routes.

Provides endpoints for time-based data retrieval and visualization support.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from app.dependencies.services import get_replay_service, get_task_stream_service
from app.schemas.simulation import (
    AllHostsSnapshotResponse,
    CallChainResponse,
    ErrorResponse,
    HostHistoryResponse,
    SimulationMetadataResponse,
    SimulationSummaryResponse,
    TargetCallChainResponse,
    TargetsResponse,
    TimelineResponse,
    VmHistoryResponse,
)
from app.services.replay_service import ReplayService
from app.services.task_stream_service import TaskStreamService

router = APIRouter(prefix="/simulations", tags=["replay"])


@router.get(
    "/{task_id}/metadata",
    response_model=SimulationMetadataResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_simulation_metadata(
    task_id: str,
    replay: ReplayService = Depends(get_replay_service),
):
    """Get simulation metadata including time range, hosts, and VM types."""
    return await replay.get_metadata(task_id)


@router.get(
    "/{task_id}/snapshot",
    response_model=AllHostsSnapshotResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_snapshot(
    task_id: str,
    sim_time: int = Query(..., description="Simulation time in milliseconds"),
    replay: ReplayService = Depends(get_replay_service),
):
    """Get all hosts' state at a specific simulation time.

    Returns the closest resource_snapshot at or before the specified time.
    """
    return await replay.get_snapshot(task_id, sim_time)


@router.get(
    "/{task_id}/timeline",
    response_model=TimelineResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_timeline(
    task_id: str,
    start_time: int = Query(..., description="Start time in milliseconds"),
    end_time: int = Query(..., description="End time in milliseconds"),
    interval_ms: int = Query(default=1000, ge=100, le=60_000),
    replay: ReplayService = Depends(get_replay_service),
):
    return await replay.get_timeline(task_id, start_time, end_time, interval_ms)


@router.get(
    "/{task_id}/summary",
    response_model=SimulationSummaryResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_summary(
    task_id: str,
    replay: ReplayService = Depends(get_replay_service),
):
    return await replay.get_summary(task_id)


@router.get(
    "/{task_id}/hosts/{host_id}/history",
    response_model=HostHistoryResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_host_history(
    task_id: str,
    host_id: str,
    start_time: int = Query(..., description="Start time in milliseconds"),
    end_time: int = Query(..., description="End time in milliseconds"),
    replay: ReplayService = Depends(get_replay_service),
):
    """Get host resource history as ECharts-compatible series data."""
    return await replay.get_host_history(
        task_id, host_id, start_time, end_time
    )


@router.get(
    "/{task_id}/vms/{vm_id}/history",
    response_model=VmHistoryResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_vm_history(
    task_id: str,
    vm_id: str,
    start_time: int = Query(..., description="Start time in milliseconds"),
    end_time: int = Query(..., description="End time in milliseconds"),
    replay: ReplayService = Depends(get_replay_service),
):
    """Get VM resource history as ECharts-compatible series data."""
    return await replay.get_vm_history(
        task_id, vm_id, start_time, end_time
    )


@router.get(
    "/{task_id}/call-chain",
    response_model=CallChainResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_call_chain(
    task_id: str,
    sim_time: int = Query(..., description="Simulation time in milliseconds"),
    replay: ReplayService = Depends(get_replay_service),
):
    """Get call chain data for visualization.

    Returns host containers, VM nodes, and VM-level links based on layer ordering.
    """
    return await replay.get_call_chain(task_id, sim_time)


@router.get(
    "/{task_id}/targets",
    response_model=TargetsResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_targets(
    task_id: str,
    sim_time: int = Query(..., description="Simulation time in milliseconds"),
    replay: ReplayService = Depends(get_replay_service),
):
    """Get list of target IDs that have call-chain data at or before sim_time."""
    targets = await replay.get_targets(task_id, sim_time)
    return {"targets": targets}


@router.get(
    "/{task_id}/target-hist",
    response_model=TargetCallChainResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_target_hist(
    task_id: str,
    sim_time: int = Query(..., description="Simulation time in milliseconds"),
    target_id: int = Query(..., description="Target ID"),
    replay: ReplayService = Depends(get_replay_service),
):
    """按 target_id 返回调用链历史（字段与旧版一致；event 由 reason_event 映射）。"""
    return await replay.get_target_call_chain(task_id, sim_time, target_id)


@router.websocket("/{task_id}/stream")
async def simulation_stream(
    websocket: WebSocket,
    task_id: str,
    streamer: TaskStreamService = Depends(get_task_stream_service),
):
    """WebSocket endpoint for real-time aligned simulation data streaming."""
    await websocket.accept()

    try:
        async for msg_type, payload in streamer.iter_messages(task_id):
            await websocket.send_json({"type": msg_type, "data": payload})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"error": str(e)})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
