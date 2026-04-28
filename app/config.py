from __future__ import annotations

import sys
from pathlib import Path
from typing import List

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if getattr(sys, 'frozen', False):
    # 打包环境：sys.executable 是 sim_backend/sim_backend.exe
    # 向上退两级，将根目录指向部署包的最外层 (即 start.bat 所在位置)
    _REPO_ROOT = Path(sys.executable).parent.parent
    _SIM_DIR_DEFAULT = Path("microserviceSim")
else:
    # 开发环境：保持原样
    _REPO_ROOT = Path(__file__).resolve().parent.parent
    _SIM_DIR_DEFAULT = Path("../microserviceSim")

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    BACKEND_ROOT: Path = Field(default_factory=lambda: _REPO_ROOT)

    # 以下所有的目录，现在都会自动建立在部署包的最外层！
    DATA_DIR: Path = Field(default_factory=lambda: Path("data"))
    SIM_PROJECT_DIR: Path = Field(default_factory=lambda: _SIM_DIR_DEFAULT)
    DB_PATH: Path = Field(default_factory=lambda: Path("data/sim_tasks.db"))
    SOURCE_DATA_DIR: Path = Field(default_factory=lambda: Path("datasources"))
    
    MVN_COMMAND: str = "mvn"
    MVN_QUIET: bool = True
    CORS_ORIGINS: List[str] = ["*"]
    MAX_CONCURRENT_TASKS: int = 5
    REPLAY_PROCESSOR_CACHE_MAX: int = 64

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
