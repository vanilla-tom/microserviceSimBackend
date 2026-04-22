from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import FileResponse

from app.dependencies.services import get_simulation_service
from app.models.task import Task, TaskStatus
from app.schemas.simulation import CreateSimulationRequest
from app.services.simulation_service import SimulationService

router = APIRouter(prefix="/simulations", tags=["simulations"])


@router.post("", status_code=200)
async def create_simulation(
    payload: CreateSimulationRequest,
    service: SimulationService = Depends(get_simulation_service),
):
    """Start a new simulation task."""
    task_id = await service.create_simulation(
        launch_params=payload.target_distribution,
    )
    return {"task_id": task_id, "status": "pending"}


@router.get("")
async def list_simulations(
    status: Optional[TaskStatus] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    service: SimulationService = Depends(get_simulation_service),
):
    """List simulation task history."""
    tasks = await service.list_tasks(status=status, limit=limit, offset=offset)
    return {"tasks": tasks}


@router.get("/{task_id}", response_model=Task)
async def get_simulation(
    task_id: str,
    service: SimulationService = Depends(get_simulation_service),
):
    """Get a task record."""
    return await service.get_task(task_id)


@router.get("/{task_id}/config")
async def get_simulation_config(
    task_id: str,
    service: SimulationService = Depends(get_simulation_service),
):
    return {
        "task_id": task_id,
        "target_distribution": await service.get_launch_params(task_id),
    }


@router.get("/{task_id}/status", response_model=Task)
async def get_simulation_status(
    task_id: str,
    service: SimulationService = Depends(get_simulation_service),
):
    """Query the status of a simulation task."""
    return await service.get_task(task_id)


@router.get("/{task_id}/result")
async def get_simulation_result(
    task_id: str,
    service: SimulationService = Depends(get_simulation_service),
):
    """Download simulation result files."""
    resolved = await service.get_primary_result_file(task_id)
    return FileResponse(
        path=str(resolved.path),
        media_type=resolved.media_type,
        filename=resolved.filename,
    )


@router.get("/{task_id}/files")
async def list_result_files(
    task_id: str,
    service: SimulationService = Depends(get_simulation_service),
):
    """List all output files for a completed task."""
    names = await service.list_result_filenames(task_id)
    return {"task_id": task_id, "files": names}


@router.get("/{task_id}/files/{filename}")
async def download_result_file(
    task_id: str,
    filename: str,
    service: SimulationService = Depends(get_simulation_service),
):
    """Download a specific output file by name."""
    resolved = await service.resolve_result_download(task_id, filename)
    return FileResponse(
        path=str(resolved.path),
        media_type=resolved.media_type,
        filename=resolved.filename,
    )


@router.delete("/{task_id}", status_code=204)
async def delete_simulation(
    task_id: str,
    service: SimulationService = Depends(get_simulation_service),
):
    """Delete a simulation record and remove its task data directory."""
    await service.delete_task(task_id)
    return Response(status_code=204)


@router.post("/{task_id}/cancel", status_code=204)
async def cancel_simulation(
    task_id: str,
    service: SimulationService = Depends(get_simulation_service),
):
    """Cancel a running or pending simulation while keeping its record."""
    await service.cancel_task(task_id)
    return Response(status_code=204)
