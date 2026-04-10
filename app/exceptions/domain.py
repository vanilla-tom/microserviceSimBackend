from __future__ import annotations


class TaskNotFoundError(Exception):
    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(f"Task not found: {task_id}")


class TaskNotReadyError(Exception):
    def __init__(self, task_id: str, current_status: str) -> None:
        self.task_id = task_id
        self.current_status = current_status
        super().__init__(
            f"Task {task_id} result not ready, current status: {current_status}"
        )


class EmptyUploadedConfigError(Exception):
    """Uploaded config file had no body."""

    pass


class DefaultConfigNotFoundError(Exception):
    """No default simulation config found in project directory."""

    pass


class SimulationCreateFailedError(Exception):
    """Unexpected failure while creating a simulation task."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class NoResultFilesError(Exception):
    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(f"No result files found for task {task_id}")


class InvalidResultFilenameError(Exception):
    def __init__(self, message: str = "Invalid filename") -> None:
        super().__init__(message)


class ResultFileNotFoundError(Exception):
    def __init__(self, filename: str) -> None:
        self.filename = filename
        super().__init__(f"File not found: {filename}")


class ReplayJsonlNotFoundError(Exception):
    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(f"No JSONL file found for task {task_id}")
