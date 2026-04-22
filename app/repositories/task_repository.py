from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence

from app.database import get_db
from app.exceptions.domain import TaskNotFoundError
from app.models.task import Task, TaskStatus


class TaskRepository:
    """SQLite persistence for simulation tasks."""

    async def create_task(
        self,
        task_id: str,
        config_path: str,
        output_dir: str,
    ) -> Task:
        db = await get_db()
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            """INSERT INTO tasks (task_id, status, config_path, output_dir, created_at)
               VALUES (?, 'pending', ?, ?, ?)""",
            (task_id, config_path, output_dir, now),
        )
        await db.commit()
        return Task(
            task_id=task_id,
            status=TaskStatus.PENDING,
            progress=0.0,
            pid=None,
            config_path=config_path,
            output_dir=output_dir,
            error_message=None,
            created_at=now,
            start_time=None,
            end_time=None,
            real_start_time=None,
        )

    async def get_task(self, task_id: str) -> Optional[Task]:
        db = await get_db()
        cursor = await db.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return Task.from_row(dict(row))

    async def list_tasks(
        self,
        *,
        status: Optional[TaskStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Task]:
        db = await get_db()
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))

        if status is None:
            cursor = await db.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (status.value, limit, offset),
            )

        rows = await cursor.fetchall()
        return [Task.from_row(dict(r)) for r in rows]

    async def set_running(self, task_id: str, pid: int) -> None:
        db = await get_db()
        now = datetime.now(timezone.utc).isoformat()
        real_start_time = int(datetime.now(timezone.utc).timestamp() * 1000)
        result = await db.execute(
            """UPDATE tasks SET status='running', pid=?, start_time=?, real_start_time=?
               WHERE task_id=? AND status='pending'""",
            (pid, now, real_start_time, task_id),
        )
        await db.commit()
        if result.rowcount == 0:
            raise TaskNotFoundError(task_id)

    async def set_completed(self, task_id: str) -> None:
        db = await get_db()
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            """UPDATE tasks SET status='completed', end_time=?, error_message=NULL, pid=NULL
               WHERE task_id=? AND status IN ('pending', 'running')""",
            (now, task_id),
        )
        await db.commit()

    async def set_failed(self, task_id: str, error_message: str) -> None:
        db = await get_db()
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            """UPDATE tasks SET status='failed', end_time=?, error_message=?, pid=NULL
               WHERE task_id=? AND status IN ('pending', 'running')""",
            (now, error_message, task_id),
        )
        await db.commit()

    async def delete_task(self, task_id: str) -> bool:
        db = await get_db()
        result = await db.execute(
            "DELETE FROM tasks WHERE task_id = ?", (task_id,)
        )
        await db.commit()
        return result.rowcount > 0

    async def recover_orphaned_tasks(self) -> int:
        """Mark any 'running' tasks as failed on startup (server crash recovery)."""
        db = await get_db()
        now = datetime.now(timezone.utc).isoformat()
        result = await db.execute(
            """UPDATE tasks SET status='failed', end_time=?,
               error_message='Server restarted, task interrupted', pid=NULL
               WHERE status='running'""",
            (now,),
        )
        await db.commit()
        return result.rowcount
