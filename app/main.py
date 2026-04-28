from __future__ import annotations

import mimetypes

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/json", ".json")

import asyncio
import logging
import platform
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse

# Windows requires ProactorEventLoop for subprocess support
if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from app.config import settings
from app.database import close_db, init_db
from app.exceptions.domain import (
    DefaultConfigNotFoundError,
    EmptyUploadedConfigError,
    InvalidResultFilenameError,
    NoResultFilesError,
    ReplayJsonlNotFoundError,
    ResultFileNotFoundError,
    SimulationCreateFailedError,
    TaskNotFoundError,
    TaskNotReadyError,
)
from app.repositories.task_repository import TaskRepository
from app.routers.detector import router as detector_router
from app.routers.replay import router as replay_router
from app.routers.resource_log import router as resource_log_router
from app.routers.simulations import router as simulations_router
from app.routers.tag_log import router as tag_log_router
from app.services import process_manager
from app.services.replay_service import ReplayService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    logger.info("Starting sim-backend...")

    # Ensure data directory exists
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Initialize database
    await init_db()
    logger.info("Database initialized at %s", settings.DB_PATH)

    # Recover orphaned tasks from previous crashes
    recovered = await TaskRepository().recover_orphaned_tasks()
    if recovered:
        logger.warning("Recovered %d orphaned task(s) from previous run", recovered)

    logger.info("sim-backend started. Simulation project: %s", settings.SIM_PROJECT_DIR.resolve())

    yield

    # --- Shutdown ---
    logger.info("Shutting down sim-backend...")
    await process_manager.shutdown_all()
    await close_db()
    ReplayService.clear_processors()
    logger.info("sim-backend stopped.")


app = FastAPI(
    title="Microservice Simulation Backend",
    description="Backend API for managing CloudSim Plus microservice simulation tasks",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(simulations_router, prefix="/api")
app.include_router(replay_router, prefix="/api")
app.include_router(resource_log_router, prefix="/api")
app.include_router(tag_log_router, prefix="/api")
app.include_router(detector_router, prefix="/api")

if getattr(sys, 'frozen', False):
    EXE_DIR = os.path.dirname(sys.executable)
    FRONTEND_DIR = os.path.abspath(os.path.join(EXE_DIR, "..", "frontend_dist"))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    FRONTEND_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "frontend_dist"))

@app.get("/")
async def serve_root():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    return JSONResponse(
        status_code=404, 
        content={"error": f"根目录找不到 index.html，当前实际查找的路径是: {index_path}"}
    )

@app.api_route("/{catchall:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"])
async def serve_spa(request: Request, catchall: str):
    if catchall.startswith("api/"):
        return JSONResponse(status_code=404, content={"error": f"前端试图请求无效的后端接口: /{catchall}"})

    # 匹配具体的静态资源文件 (如 .js, .css, .png)
    file_path = os.path.join(FRONTEND_DIR, catchall)
    if catchall != "" and os.path.isfile(file_path):
        return FileResponse(file_path)
    
    # 根路径 "/" 或 前端页面路由回退，读取 index.html 返回 HTML
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.isfile(index_path):
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                html_content = f.read()
            # 使用 HTMLResponse 彻底杜绝底层框架乱报 404 的可能
            return HTMLResponse(content=html_content, status_code=200)
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": f"读取 index.html 失败: {str(e)}"})
    
    return JSONResponse(
        status_code=404, 
        content={"error": f"致命错误: 在 {FRONTEND_DIR} 下找不到 index.html。请检查 frontend_dist 内部结构！"}
    )

# --- Global Exception Handlers ---

@app.exception_handler(TaskNotFoundError)
async def task_not_found_handler(request: Request, exc: TaskNotFoundError):
    return JSONResponse(status_code=404, content={"error": str(exc)})


@app.exception_handler(TaskNotReadyError)
async def task_not_ready_handler(request: Request, exc: TaskNotReadyError):
    return JSONResponse(status_code=409, content={"error": str(exc)})


@app.exception_handler(EmptyUploadedConfigError)
async def empty_uploaded_config_handler(
    request: Request, exc: EmptyUploadedConfigError
):
    return JSONResponse(
        status_code=400,
        content={"error": "Uploaded config file is empty"},
    )


@app.exception_handler(DefaultConfigNotFoundError)
async def default_config_not_found_handler(
    request: Request, exc: DefaultConfigNotFoundError
):
    return JSONResponse(status_code=400, content={"error": str(exc)})


@app.exception_handler(SimulationCreateFailedError)
async def simulation_create_failed_handler(
    request: Request, exc: SimulationCreateFailedError
):
    return JSONResponse(
        status_code=500,
        content={"error": f"Failed to create task: {exc.message}"},
    )


@app.exception_handler(NoResultFilesError)
async def no_result_files_handler(request: Request, exc: NoResultFilesError):
    return JSONResponse(status_code=404, content={"error": str(exc)})


@app.exception_handler(InvalidResultFilenameError)
async def invalid_result_filename_handler(
    request: Request, exc: InvalidResultFilenameError
):
    return JSONResponse(status_code=400, content={"error": str(exc)})


@app.exception_handler(ResultFileNotFoundError)
async def result_file_not_found_handler(
    request: Request, exc: ResultFileNotFoundError
):
    return JSONResponse(status_code=404, content={"error": str(exc)})


@app.exception_handler(ReplayJsonlNotFoundError)
async def replay_jsonl_not_found_handler(
    request: Request, exc: ReplayJsonlNotFoundError
):
    return JSONResponse(status_code=404, content={"error": str(exc)})


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500, content={"error": "Internal server error"}
    )


@app.get("/health")
async def health_check():
    return {"status": "ok"}
