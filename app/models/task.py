from __future__ import annotations

import enum
from typing import Optional

from pydantic import BaseModel


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Task(BaseModel):
    task_id: str
    status: TaskStatus
    progress: float = 0.0
    pid: Optional[int] = None
    config_path: Optional[str] = None
    output_dir: Optional[str] = None
    error_message: Optional[str] = None
    created_at: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    real_start_time: Optional[int] = None  # 现实开始时间戳（毫秒）

    @classmethod
    def from_row(cls, row: dict) -> Task:
        return cls(
            task_id=row["task_id"],
            status=TaskStatus(row["status"]),
            progress=row["progress"] or 0.0,
            pid=row["pid"],
            config_path=row["config_path"],
            output_dir=row["output_dir"],
            error_message=row["error_message"],
            created_at=row["created_at"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            real_start_time=row.get("real_start_time"),
        )