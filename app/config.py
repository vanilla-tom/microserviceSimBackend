from __future__ import annotations

from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    DATA_DIR: Path = Path("./data")
    SIM_PROJECT_DIR: Path = Path("../microservice-sim")
    DB_PATH: Path = Path("./data/sim_tasks.db")
    MVN_COMMAND: str = "mvn"
    MVN_QUIET: bool = True
    CORS_ORIGINS: List[str] = ["*"]
    MAX_CONCURRENT_TASKS: int = 5


settings = Settings()
