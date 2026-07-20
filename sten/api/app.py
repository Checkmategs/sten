"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from sten.api.meetings import router as meetings_router
from sten.db import init_db


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Sten", lifespan=lifespan)
    app.include_router(meetings_router)
    return app


app = create_app()
