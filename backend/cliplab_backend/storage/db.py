from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from uuid import uuid4

from cliplab_backend.schemas import LogRecord, TaskRecord


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    input TEXT NOT NULL,
                    output_path TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS logs (
                    id TEXT PRIMARY KEY,
                    level TEXT NOT NULL,
                    source TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    task_id TEXT,
                    context TEXT NOT NULL
                )
                """
            )


class TaskRepository:
    def __init__(self, database: Database):
        self.database = database

    def save(self, task: TaskRecord) -> TaskRecord:
        with self.database.connection() as conn:
            conn.execute(
                """
                INSERT INTO tasks (
                    id, type, status, progress, input, output_path, error_code, error_message,
                    created_at, updated_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    progress=excluded.progress,
                    output_path=excluded.output_path,
                    error_code=excluded.error_code,
                    error_message=excluded.error_message,
                    updated_at=excluded.updated_at,
                    metadata=excluded.metadata
                """,
                (
                    task.id,
                    task.type,
                    task.status,
                    task.progress,
                    task.input,
                    task.outputPath,
                    task.errorCode,
                    task.errorMessage,
                    task.createdAt.isoformat(),
                    task.updatedAt.isoformat(),
                    json.dumps(task.metadata)
                ),
            )
        return task

    def list(self) -> list[TaskRecord]:
        with self.database.connection() as conn:
            rows = conn.execute("SELECT * FROM tasks ORDER BY updated_at DESC").fetchall()
        return [self._row_to_task(row) for row in rows]

    def get(self, task_id: str) -> TaskRecord | None:
        with self.database.connection() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    def interrupt_in_flight_tasks(self) -> None:
        now = utcnow().isoformat()
        with self.database.connection() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = 'interrupted', updated_at = ?
                WHERE status IN ('queued', 'running')
                """,
                (now,),
            )

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> TaskRecord:
        return TaskRecord(
            id=row["id"],
            type=row["type"],
            status=row["status"],
            progress=row["progress"],
            input=row["input"],
            outputPath=row["output_path"],
            errorCode=row["error_code"],
            errorMessage=row["error_message"],
            createdAt=datetime.fromisoformat(row["created_at"]),
            updatedAt=datetime.fromisoformat(row["updated_at"]),
            metadata=json.loads(row["metadata"]),
        )


class LogRepository:
    def __init__(self, database: Database):
        self.database = database

    def create(
        self,
        *,
        level: str,
        source: str,
        message: str,
        task_id: str | None = None,
        context: dict | None = None,
    ) -> LogRecord:
        record = LogRecord(
            id=str(uuid4()),
            level=level,
            source=source,
            message=message,
            createdAt=utcnow(),
            taskId=task_id,
            context=context or {},
        )
        with self.database.connection() as conn:
            conn.execute(
                """
                INSERT INTO logs (id, level, source, message, created_at, task_id, context)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.level,
                    record.source,
                    record.message,
                    record.createdAt.isoformat(),
                    record.taskId,
                    json.dumps(record.context),
                ),
            )
        return record

    def list(self, limit: int = 50) -> list[LogRecord]:
        with self.database.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM logs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_log(row) for row in rows]

    @staticmethod
    def _row_to_log(row: sqlite3.Row) -> LogRecord:
        return LogRecord(
            id=row["id"],
            level=row["level"],
            source=row["source"],
            message=row["message"],
            createdAt=datetime.fromisoformat(row["created_at"]),
            taskId=row["task_id"],
            context=json.loads(row["context"]),
        )
