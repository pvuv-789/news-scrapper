"""
FastAPI application entrypoint.
SRP: ONLY handles app wiring — mounts router, CORS, lifespan events.
"""
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from api.router import api_router
from core.config import get_settings
from core.database import engine
from core.logging_config import configure_logging
from models.db_models import Base

_settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan handler:
    - Startup: configure logging, ensure DB tables exist.
    - Shutdown: dispose DB connection pool.
    """
    configure_logging(debug=_settings.app_debug)

    # Create all tables (dev only; use Alembic in production)
    if _settings.app_env == "development":
        async with engine.begin() as conn:
            # Ensure pg_trgm extension is available for similarity search
            await conn.execute(
                __import__("sqlalchemy").text("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
            )
            await conn.run_sync(Base.metadata.create_all)

    yield

    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="E-Paper News Aggregation API",
        description=(
            "Automated news scraping, NLP processing, and visualization API "
            "targeting Daily Thanthi E-Paper."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # CORS — allow Vue.js dev server and any configured origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount all API routes
    app.include_router(api_router)

    @app.get("/health", tags=["System"])
    async def health_check():
        return {"status": "ok", "env": _settings.app_env}

    # Serve the newspaper viewer HTML at /viewer (same-origin as the API)
    _html_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "thanthi_layout.html",
    )

    @app.get("/viewer", tags=["Viewer"])
    async def newspaper_viewer():
        """Serve the Daily Thanthi newspaper layout viewer."""
        if not os.path.isfile(_html_path):
            raise HTTPException(
                status_code=404,
                detail="Viewer not found. Run gen_html.py first to generate thanthi_layout.html.",
            )
        return FileResponse(_html_path, media_type="text/html")

    # Serve the classifieds image viewer
    _classifieds_html_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "classifieds_viewer.html",
    )

    @app.get("/viewer/classifieds", tags=["Viewer"])
    async def classifieds_viewer():
        """Serve the classified ads image viewer page."""
        if not os.path.isfile(_classifieds_html_path):
            raise HTTPException(
                status_code=404,
                detail="Classifieds viewer not found.",
            )
        return FileResponse(_classifieds_html_path, media_type="text/html")

    return app


app = create_app()
