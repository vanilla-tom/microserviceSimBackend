from __future__ import annotations

from pathlib import Path
from typing import List

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Directory that contains the `app` package (repository root when installed from source)
_REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # Anchor for resolving relative DATA_DIR / SIM_PROJECT_DIR / DB_PATH (default: this repo)
    BACKEND_ROOT: Path = Field(default_factory=lambda: _REPO_ROOT)

    DATA_DIR: Path = Field(default_factory=lambda: Path("data"))
    SIM_PROJECT_DIR: Path = Field(default_factory=lambda: Path("../microserviceSim"))
    DB_PATH: Path = Field(default_factory=lambda: Path("data/sim_tasks.db"))
    MVN_COMMAND: str = "mvn"
    MVN_QUIET: bool = True
    CORS_ORIGINS: List[str] = ["*"]
    MAX_CONCURRENT_TASKS: int = 5

    # Replay: max parsed JSONL processors kept in memory (LRU by last access). <=0 = unlimited.
    REPLAY_PROCESSOR_CACHE_MAX: int = 64

    # Simulation workload CSV directory (relative paths use BACKEND_ROOT)
    SOURCE_DATA_DIR: Path = Field(default_factory=lambda: Path("datasources"))

    @model_validator(mode="after")
    def _resolve_paths(self) -> Settings:
        root = self.BACKEND_ROOT
        if not root.is_absolute():
            root = (_REPO_ROOT / root).resolve()
        else:
            root = root.resolve()
        self.BACKEND_ROOT = root

        if not self.DATA_DIR.is_absolute():
            self.DATA_DIR = (root / self.DATA_DIR).resolve()
        else:
            self.DATA_DIR = self.DATA_DIR.resolve()

        if not self.SIM_PROJECT_DIR.is_absolute():
            self.SIM_PROJECT_DIR = (root / self.SIM_PROJECT_DIR).resolve()
        else:
            self.SIM_PROJECT_DIR = self.SIM_PROJECT_DIR.resolve()

        if not self.DB_PATH.is_absolute():
            self.DB_PATH = (root / self.DB_PATH).resolve()
        else:
            self.DB_PATH = self.DB_PATH.resolve()

        if not self.SOURCE_DATA_DIR.is_absolute():
            self.SOURCE_DATA_DIR = (root / self.SOURCE_DATA_DIR).resolve()
        else:
            self.SOURCE_DATA_DIR = self.SOURCE_DATA_DIR.resolve()

        return self


settings = Settings()
