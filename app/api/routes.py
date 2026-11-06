import os
import uuid
import json
import logging
import aiofiles
from pathlib import Path
from typing import Optional, List
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from app.core.config import settings
from app.core.database import get_db
from app.models.schemas import (
    CharacterCreate, CharacterResponse, StoryboardRequest, StoryboardResponse,
    ProjectResponse, ShotResponse, GenerateVideoRequest, VideoGenerationResult,
    HealthResponse, SceneTemplate, ProjectStatus, ShotStatus
)
from app.services.vision import extract_character_description
from app.services.local_context import list_templates, get_template_by_id
from app.services.storyboard import generate_storyboard
from app.services.image_gen import generate_image, make_seed_from_text
from app.services.video_gen import generate_video_from_image
from app.services.assembler import assemble_final_video

logger = logging.getLogger(__name__)
router = APIRouter()

# Ensure dirs exist
Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
Path(settings.output_dir).mkdir(parents=True, exist_ok=True)


@router.get("/health", response_model=HealthResponse)
async def health():
    services = {
        "database": "ok",
        "groq": "configured" if settings.groq_api_key else "missing_key",
        "magic_hour": "configured" if settings.magic_hour_api_key else "missing_key",
        "agnes_ai": "configured" if settings.agnes_ai_api_key else "missing_key",
        "pollinations": "ok (no key needed)",
        "ffmpeg": "assumed available",
    }
    return HealthResponse(status="ok", version="1.0.0", services=services)


# ---------------------------------------------------------------------------
# Characters (Consistency Engine)
# ---------------------------------------------------------------------------

@router.post("/characters", response_model=CharacterResponse)
async def create_character(
    name: str = Form(...),
    style_tags: Optional[str] = Form(None),
    extra_hints: Optional[str] = Form(None),
    image: UploadFile = File(...),
):
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(400, "Le fichier doit être une image")

    content = await image.read()
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(400, f"Image trop grande (max {settings.max_upload_size_mb}MB)")

    char_id = str(uuid.uuid4())
    ext = Path(image.filename or "photo.jpg").suffix.lower() or ".jpg"
    image_filename = f"{char_id}{ext}"
    image_path = os.path.join(settings.upload_dir, image_filename)

    async with aiofiles.open(image_path, "wb") as f:
        await f.write(content)

    description, auto_tags = await extract_character_description(content, name, extra_hints)
    final_tags = style_tags or auto_tags

    db = await get_db()
    await db.execute(
        """
        INSERT INTO characters (id, name, description, image_path, style_tags)
        VALUES (?, ?, ?, ?, ?)
        """,
        [char_id, name, description, image_path, final_tags],
    )

    rows = await db.execute("SELECT * FROM characters WHERE id = ?", [char_id])
    row = rows.rows[0]
    return CharacterResponse(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        image_path=row["image_path"],
        style_tags=row["style_tags"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.get("/characters", response_model=List[CharacterResponse])
async def list_characters():
    db = await get_db()
    result = await db.execute("SELECT * FROM characters ORDER BY created_at DESC")
    return [
        CharacterResponse(
            id=r["id"], name=r["name"], description=r["description"],
            image_path=r["image_path"], style_tags=r["style_tags"],
            created_at=r["created_at"], updated_at=r["updated_at"],
        )
        for r in result.rows
    ]


@router.get("/characters/{character_id}", response_model=CharacterResponse)
async def get_character(character_id: str):
    db = await get_db()
    result = await db.execute("SELECT * FROM characters WHERE id = ?", [character_id])
    if not result.rows:
        raise HTTPException(404, "Personnage non trouvé")
    r = result.rows[0]
    return CharacterResponse(
        id=r["id"], name=r["name"], description=r["description"],
        image_path=r["image_path"], style_tags=r["style_tags"],
        created_at=r["created_at"], updated_at=r["updated_at"],
    )


@router.delete("/characters/{character_id}")
async def delete_character(character_id: str):
    db = await get_db()
    result = await db.execute("SELECT image_path FROM characters WHERE id = ?", [character_id])
    if not result.rows:
        raise HTTPException(404, "Personnage non trouvé")
    img = result.rows[0]["image_path"]
    await db.execute("DELETE FROM characters WHERE id = ?", [character_id])
    if img and os.path.exists(img):
        try:
            os.remove(img)
        except OSError:
            pass
    return {"ok": True}


# ---------------------------------------------------------------------------
# Scene templates (Local Context Booster)
# ---------------------------------------------------------------------------

@router.get("/templates", response_model=List[SceneTemplate])
async def get_templates():
    templates = list_templates()
    return [SceneTemplate(**t) for t in templates]


@router.get("/templates/{template_id}", response_model=SceneTemplate)
async def get_template(template_id: str):
    t = get_template_by_id(template_id)
    if not t:
        raise HTTPException(404, "Template non trouvé")
    return SceneTemplate(**t)


# ---------------------------------------------------------------------------
# Storyboard Generator
# ---------------------------------------------------------------------------

@router.post("/storyboard", response_model=StoryboardResponse)
async def create_storyboard(req: StoryboardRequest):
    db = await get_db()

    character_description = None
    character_style_tags = None
    if req.character_id:
        res = await db.execute("SELECT description, style_tags FROM characters WHERE id = ?", [req.character_id])
        if not res.rows:
            raise HTTPException(404, "Personnage non trouvé")
        character_description = res.rows[0]["description"]
        character_style_tags = res.rows[0]["style_tags"]

    sb = await generate_storyboard(
        script=req.script,
        title=req.title,
        character_description=character_description,
        character_style_tags=character_style_tags,
        scene_template_id=req.scene_template_id,
        target_duration=req.target_duration_seconds,
        style=req.style,
        language=req.language,
    )

    project_id = str(uuid.uuid4())
    await db.execute(
        """
        INSERT INTO projects (id, title, script, character_id, language, status, storyboard_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [project_id, req.title, req.script, req.character_id, req.language, ProjectStatus.DRAFT.value, json.dumps(sb)],
    )

    shots_resp = []
    for shot in sb.get("shots", []):
        shot_id = str(uuid.uuid4())
        await db.execute(
            """
            INSERT INTO shots (id, project_id, shot_number, description, visual_prompt, duration_seconds, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                shot_id, project_id, shot["shot_number"], shot["description"],
                shot["visual_prompt"], shot.get("duration_seconds", 3.0), ShotStatus.PENDING.value,
            ],
        )
        shots_resp.append(ShotResponse(
            id=shot_id,
            project_id=project_id,
            shot_number=shot["shot_number"],
            description=shot["description"],
            visual_prompt=shot["visual_prompt"],
            duration_seconds=shot.get("duration_seconds", 3.0),
            status=ShotStatus.PENDING,
            created_at="",
        ))

    return StoryboardResponse(
        project_id=project_id,
        title=req.title,
        status=ProjectStatus.DRAFT,
        shots=shots_resp,
        message="Storyboard généré avec succès",
    )


# ---------------------------------------------------------------------------
# Full pipeline: images + videos + assemble
# ---------------------------------------------------------------------------

async def _run_full_pipeline(project_id: str):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE projects SET status = ?, updated_at = datetime('now') WHERE id = ?",
            [ProjectStatus.PROCESSING.value, project_id],
        )

        # Load project + character
        proj = await db.execute("SELECT * FROM projects WHERE id = ?", [project_id])
        if not proj.rows:
            return
        project = proj.rows[0]
        character_description = None
        if project["character_id"]:
            c = await db.execute("SELECT description FROM characters WHERE id = ?", [project["character_id"]])
            if c.rows:
                character_description = c.rows[0]["description"]

        shots_res = await db.execute(
            "SELECT * FROM shots WHERE project_id = ? ORDER BY shot_number", [project_id]
        )
        shots = shots_res.rows

        video_paths = []
        for shot in shots:
            shot_id = shot["id"]
            prompt = shot["visual_prompt"]
            duration = float(shot["duration_seconds"] or 3.0)

            # Image
            await db.execute(
                "UPDATE shots SET status = ? WHERE id = ?",
                [ShotStatus.GENERATING_IMAGE.value, shot_id],
            )
            img_path = os.path.join(settings.output_dir, project_id, f"shot_{shot['shot_number']:02d}.jpg")
            seed = make_seed_from_text(prompt + (character_description or ""))
            await generate_image(prompt, img_path, seed=seed)
            await db.execute(
                "UPDATE shots SET image_url = ?, status = ? WHERE id = ?",
                [img_path, ShotStatus.GENERATING_VIDEO.value, shot_id],
            )

            # Video
            vid_path = os.path.join(settings.output_dir, project_id, f"shot_{shot['shot_number']:02d}.mp4")
            await generate_video_from_image(
                img_path, prompt, vid_path, duration_seconds=duration,
                character_description=character_description,
            )
            await db.execute(
                "UPDATE shots SET video_url = ?, status = ? WHERE id = ?",
                [vid_path, ShotStatus.READY.value, shot_id],
            )
            video_paths.append(vid_path)

        # Assemble
        final_path = os.path.join(settings.output_dir, project_id, "final.mp4")
        await assemble_final_video(video_paths, final_path)

        await db.execute(
            "UPDATE projects SET status = ?, video_path = ?, updated_at = datetime('now') WHERE id = ?",
            [ProjectStatus.COMPLETED.value, final_path, project_id],
        )
        logger.info(f"Project {project_id} completed successfully")

    except Exception as e:
        logger.exception(f"Pipeline failed for {project_id}")
        await db.execute(
            "UPDATE projects SET status = ?, updated_at = datetime('now') WHERE id = ?",
            [ProjectStatus.FAILED.value, project_id],
        )


@router.post("/projects/{project_id}/generate", response_model=VideoGenerationResult)
async def generate_project_video(project_id: str, background_tasks: BackgroundTasks):
    db = await get_db()
    res = await db.execute("SELECT * FROM projects WHERE id = ?", [project_id])
    if not res.rows:
        raise HTTPException(404, "Projet non trouvé")

    status = res.rows[0]["status"]
    if status == ProjectStatus.PROCESSING.value:
        return VideoGenerationResult(
            project_id=project_id,
            status=ProjectStatus.PROCESSING,
            message="Génération déjà en cours",
        )

    background_tasks.add_task(_run_full_pipeline, project_id)
    return VideoGenerationResult(
        project_id=project_id,
        status=ProjectStatus.PROCESSING,
        message="Génération lancée en arrière-plan",
    )


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str):
    db = await get_db()
    res = await db.execute("SELECT * FROM projects WHERE id = ?", [project_id])
    if not res.rows:
        raise HTTPException(404, "Projet non trouvé")
    p = res.rows[0]

    shots_res = await db.execute(
        "SELECT * FROM shots WHERE project_id = ? ORDER BY shot_number", [project_id]
    )
    shots = [
        ShotResponse(
            id=s["id"], project_id=s["project_id"], shot_number=s["shot_number"],
            description=s["description"], visual_prompt=s["visual_prompt"],
            duration_seconds=s["duration_seconds"], image_url=s["image_url"],
            video_url=s["video_url"], status=s["status"], created_at=s["created_at"],
        )
        for s in shots_res.rows
    ]

    return ProjectResponse(
        id=p["id"], title=p["title"], script=p["script"],
        character_id=p["character_id"], language=p["language"],
        status=p["status"], storyboard_json=p["storyboard_json"],
        video_path=p["video_path"], created_at=p["created_at"],
        updated_at=p["updated_at"], shots=shots,
    )


@router.get("/projects", response_model=List[ProjectResponse])
async def list_projects():
    db = await get_db()
    res = await db.execute("SELECT * FROM projects ORDER BY created_at DESC LIMIT 50")
    return [
        ProjectResponse(
            id=p["id"], title=p["title"], script=p["script"],
            character_id=p["character_id"], language=p["language"],
            status=p["status"], storyboard_json=p["storyboard_json"],
            video_path=p["video_path"], created_at=p["created_at"],
            updated_at=p["updated_at"],
        )
        for p in res.rows
    ]


@router.get("/media/{project_id}/{filename}")
async def get_media(project_id: str, filename: str):
    path = os.path.join(settings.output_dir, project_id, filename)
    if not os.path.exists(path):
        # Also try uploads
        path = os.path.join(settings.upload_dir, filename)
    if not os.path.exists(path):
        raise HTTPException(404, "Fichier non trouvé")
    return FileResponse(path)


@router.get("/characters/{character_id}/image")
async def get_character_image(character_id: str):
    db = await get_db()
    res = await db.execute("SELECT image_path FROM characters WHERE id = ?", [character_id])
    if not res.rows or not res.rows[0]["image_path"]:
        raise HTTPException(404, "Image non trouvée")
    path = res.rows[0]["image_path"]
    if not os.path.exists(path):
        raise HTTPException(404, "Fichier image manquant")
    return FileResponse(path)
