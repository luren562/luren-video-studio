from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .admin import ensure_default_admin
from .api import router as api_router
from .config import get_settings
from .database import SessionLocal, engine
from .migrations import seed_defaults, upgrade_database
from .routers.ai import router as ai_router
from .routers.cover import router as cover_router
from .routers.media_assets import router as media_assets_router
from .routers.ops import router as ops_router
from .routers.outputs import media_router as outputs_media_router
from .routers.outputs import router as outputs_router
from .routers.projects import router as projects_router
from .routers.settings import router as settings_router
from .routers.strategies import router as strategies_router
from .routers.stream import router as stream_router
from .routers.styles import router as styles_router
from .routers.tasks import router as tasks_router
from .routers.transcriptions import media_router as transcriptions_media_router
from .routers.transcriptions import router as transcriptions_router
from .routers.tts import router as tts_router
from .toolchain import ensure_tool_paths
from .worker import PipelineWorker

worker = PipelineWorker()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    ensure_tool_paths()
    for directory in (
        settings.data_dir,
        settings.projects_dir,
        settings.assets_dir,
        settings.renders_dir,
        settings.uploads_dir,
        settings.transcripts_dir,
        settings.logs_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    if settings.is_sqlite:
        from pathlib import Path

        Path(settings.database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)

    upgrade_database()
    with SessionLocal() as session:
        ensure_default_admin(session)
    seed_defaults()

    if settings.worker_enabled and settings.pipeline_worker_enabled:
        worker.start()
    yield
    worker.stop()


settings = get_settings()
app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(ai_router)
app.include_router(cover_router)
app.include_router(styles_router)
app.include_router(strategies_router)
app.include_router(projects_router)
app.include_router(stream_router)
app.include_router(tasks_router)
app.include_router(media_assets_router)
app.include_router(outputs_router)
app.include_router(outputs_media_router)
app.include_router(ops_router)
app.include_router(settings_router)
app.include_router(tts_router)
app.include_router(transcriptions_router)
app.include_router(transcriptions_media_router)


@app.get("/health")
def health() -> dict:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok"}
