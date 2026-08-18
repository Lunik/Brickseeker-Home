"""FastAPI application factory.

One container serves both halves: `/api/**` is this app, everything else is the built Vite
bundle mounted as static files with an SPA fallback, so a deep link like `/collection` reloads
correctly instead of 404-ing.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import init_db, session_scope
from .routers import (
    alerts,
    auth,
    catalog,
    collection,
    history,
    images,
    notifications,
    prices,
    scan,
    sets,
    stats,
    wishlist,
)
from .routers import (
    settings as settings_router,
)
from .services.price_updater import price_updater
from .services.scheduler import shutdown_scheduler, start_scheduler
from .services.scraping.browser import shutdown_browser

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("brickseeker")

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.ensure_dirs()
    await init_db()
    # The batch updater's state is in memory; its last completion date is not, and Statistiques
    # shows it. Reload it before serving, or a restart claims the prices were never refreshed.
    async with session_scope() as session:
        await price_updater.restore(session)
    logger.info("BrickSeeker démarré — données dans %s", settings.data_dir)
    if settings.background_refresh_enabled:
        start_scheduler()
    yield
    shutdown_scheduler()
    await shutdown_browser()


def create_app() -> FastAPI:
    app = FastAPI(
        title="BrickSeeker",
        description=(
            "Scanne des sets LEGO®, gère ta collection Rebrickable et ta liste cadeaux Brickset, "
            "et compare les prix entre lego.com, BrickLink, Amazon et Cdiscount."
        ),
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    for router in (
        auth.router,
        settings_router.router,
        sets.router,
        collection.router,
        history.router,
        wishlist.router,
        prices.router,
        alerts.router,
        stats.router,
        catalog.router,
        scan.router,
        images.router,
        notifications.router,
    ):
        app.include_router(router, prefix="/api")

    @app.get("/api/health", tags=["système"])
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "scraping": settings.scraping_enabled,
            "ocr": settings.ocr_enabled,
            "backgroundRefresh": settings.background_refresh_enabled,
        }

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    """Serves the built SPA, when one was bundled. Missing in a dev container that only runs the
    API — say so plainly rather than 404-ing with no explanation."""
    if not STATIC_DIR.exists():

        @app.get("/", include_in_schema=False)
        async def missing_frontend() -> JSONResponse:
            return JSONResponse(
                {
                    "detail": (
                        "Interface non compilée. Lance `npm run build` dans frontend/, "
                        "ou utilise le serveur de dev Vite."
                    )
                },
                status_code=503,
            )

        return

    assets = STATIC_DIR / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    # `response_model=None`: FastAPI otherwise tries to build a response model from the union
    # return annotation, which is not a valid Pydantic type and fails at startup.
    @app.get("/{full_path:path}", include_in_schema=False, response_model=None)
    async def spa(full_path: str) -> FileResponse | JSONResponse:
        # Anything under /api that reached here is a genuine miss, not a client route.
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Ressource introuvable"}, status_code=404)
        # Resolve before testing: `full_path` is user input, and a `..` segment that survived URL
        # normalisation would otherwise read any file the process can see.
        candidate = (STATIC_DIR / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(STATIC_DIR.resolve()):
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")


app = create_app()
