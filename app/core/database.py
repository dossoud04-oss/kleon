import os
from typing import Optional, Any, List, Dict
from libsql_client import create_client, Client
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

_client: Optional[Client] = None


async def get_db() -> Client:
    global _client
    if _client is None:
        if not settings.turso_database_url or not settings.turso_auth_token:
            # Fallback to local SQLite file for development without Turso
            local_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "kleos.db")
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            _client = create_client(url=f"file:{local_path}")
            logger.warning("Using local SQLite fallback (no Turso credentials)")
        else:
            _client = create_client(
                url=settings.turso_database_url,
                auth_token=settings.turso_auth_token,
            )
        await init_db(_client)
    return _client


async def init_db(client: Client) -> None:
    """Create tables if they do not exist."""
    statements = [
        """
        CREATE TABLE IF NOT EXISTS characters (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            image_path TEXT,
            style_tags TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            script TEXT NOT NULL,
            character_id TEXT,
            language TEXT DEFAULT 'fr',
            status TEXT DEFAULT 'draft',
            storyboard_json TEXT,
            video_path TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (character_id) REFERENCES characters(id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS shots (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            shot_number INTEGER NOT NULL,
            description TEXT NOT NULL,
            visual_prompt TEXT NOT NULL,
            duration_seconds REAL DEFAULT 3.0,
            image_url TEXT,
            video_url TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (project_id) REFERENCES projects(id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS scene_templates (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            location TEXT NOT NULL,
            country TEXT NOT NULL,
            description TEXT NOT NULL,
            visual_keywords TEXT NOT NULL,
            cultural_notes TEXT
        )
        """,
    ]
    for stmt in statements:
        await client.execute(stmt)
    logger.info("Database initialized")


async def close_db() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
