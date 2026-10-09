"""FastAPI application factory."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from sten.api.auth import router as auth_router
from sten.api.meetings import router as meetings_router
from sten.db import init_db

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Sten", lifespan=lifespan)
    app.include_router(auth_router)
    app.include_router(meetings_router)

    if WEB_DIST.is_dir():
        assets = WEB_DIST / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

        @app.get("/")
        async def spa_root():
            return FileResponse(WEB_DIST / "index.html")

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            # API уже на /api/* через router; сюда доходят только UI-пути.
            candidate = (WEB_DIST / full_path).resolve()
            try:
                candidate.relative_to(WEB_DIST.resolve())
            except ValueError:
                return FileResponse(WEB_DIST / "index.html")
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(WEB_DIST / "index.html")

    return app


app = create_app()
