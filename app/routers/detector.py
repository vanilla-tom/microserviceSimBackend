from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.dependencies.services import get_task_repository
from app.exceptions.domain import TaskNotFoundError
from app.repositories.task_repository import TaskRepository
from app.schemas.detector import DetectorDatasResponse, DetectorListResponse
from app.services.detector_service import (
    DetectorError,
    load_detector_datas,
    load_detector_list,
)

router = APIRouter(tags=["detector"])


@router.get("/detectorList", response_model=DetectorListResponse)
async def get_detector_list(
    task_id: str = Query(..., description="仿真任务 ID（与创建任务时返回的 task_id 一致）"),
    repo: TaskRepository = Depends(get_task_repository),
):
    task = await repo.get_task(task_id)
    if task is None:
        raise TaskNotFoundError(task_id)
    try:
        return await asyncio.to_thread(load_detector_list, task)
    except DetectorError as e:
        return JSONResponse(status_code=e.status_code, content={"error": e.message})


@router.get("/detector", response_model=DetectorDatasResponse)
async def get_detector_data(
    task_id: str = Query(..., description="仿真任务 ID（与创建任务时返回的 task_id 一致）"),
    sim_time: int = Query(..., ge=0, description="仿真时间上界（毫秒，含）"),
    sensor_id: int = Query(..., description="传感器编号", alias="id"),
    repo: TaskRepository = Depends(get_task_repository),
):
    task = await repo.get_task(task_id)
    if task is None:
        raise TaskNotFoundError(task_id)
    try:
        return await asyncio.to_thread(load_detector_datas, task, sim_time, sensor_id)
    except DetectorError as e:
        return JSONResponse(status_code=e.status_code, content={"error": e.message})
