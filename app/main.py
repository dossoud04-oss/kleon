import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.core.config import settings
from app.core.database import get_db, close_db
from app.api.routes import router
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("kleos")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Kleos backend...")
    os.makedirs(settings.upload_dir, exist_ok=True)
    os.makedirs(settings.output_dir, exist_ok=True)
    await get_db()
    logger.info("Database ready")
    yield
    await close_db()
    logger.info("Kleos backend stopped")


app = FastAPI(
    title="Kleos API",
    description="Génération de publicités vidéo courtes pour créateurs africains francophones",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")

# Serve generated media
if os.path.isdir(settings.output_dir):
    app.mount("/outputs", StaticFiles(directory=settings.output_dir), name="outputs")
if os.path.isdir(settings.upload_dir):
    app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")


@app.get("/")
async def root():
    return {
        "app": "Kleos",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/api/v1/health",
    }
