from __future__ import annotations

from fastapi import Depends

from app.repositories.task_repository import TaskRepository
from app.services.replay_service import ReplayService
from app.services.simulation_service import SimulationService
from app.services.task_stream_service import TaskStreamService


def get_task_repository() -> TaskRepository:
    return TaskRepository()


def get_simulation_service(
    repo: TaskRepository = Depends(get_task_repository),
) -> SimulationService:
    return SimulationService(repo)


def get_replay_service(
    repo: TaskRepository = Depends(get_task_repository),
) -> ReplayService:
    return ReplayService(repo)


def get_task_stream_service(
    repo: TaskRepository = Depends(get_task_repository),
    replay: ReplayService = Depends(get_replay_service),
) -> TaskStreamService:
    return TaskStreamService(repo, replay)
