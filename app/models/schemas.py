from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class ProjectStatus(str, Enum):
    DRAFT = "draft"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    COMPLETED = "completed"


class ShotStatus(str, Enum):
    PENDING = "pending"
    GENERATING_IMAGE = "generating_image"
    GENERATING_VIDEO = "generating_video"
    READY = "ready"
    FAILED = "failed"


class CharacterCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    style_tags: Optional[str] = None


class CharacterResponse(BaseModel):
    id: str
    name: str
    description: str
    image_path: Optional[str] = None
    style_tags: Optional[str] = None
    created_at: str
    updated_at: str


class SceneTemplate(BaseModel):
    id: str
    name: str
    location: str
    country: str
    description: str
    visual_keywords: str
    cultural_notes: Optional[str] = None


class ShotBase(BaseModel):
    shot_number: int
    description: str
    visual_prompt: str
    duration_seconds: float = 3.0


class ShotResponse(ShotBase):
    id: str
    project_id: str
    image_url: Optional[str] = None
    video_url: Optional[str] = None
    status: ShotStatus = ShotStatus.PENDING
    created_at: str


class StoryboardRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    script: str = Field(..., min_length=10)
    character_id: Optional[str] = None
    language: str = "fr"
    target_duration_seconds: int = Field(default=30, ge=10, le=120)
    scene_template_id: Optional[str] = None
    style: str = "cinematic realistic african"


class StoryboardResponse(BaseModel):
    project_id: str
    title: str
    status: ProjectStatus
    shots: List[ShotResponse]
    message: str


class ProjectResponse(BaseModel):
    id: str
    title: str
    script: str
    character_id: Optional[str] = None
    language: str
    status: ProjectStatus
    storyboard_json: Optional[str] = None
    video_path: Optional[str] = None
    created_at: str
    updated_at: str
    shots: Optional[List[ShotResponse]] = None


class GenerateVideoRequest(BaseModel):
    project_id: str
    force_regenerate: bool = False


class VideoGenerationResult(BaseModel):
    project_id: str
    status: ProjectStatus
    video_url: Optional[str] = None
    message: str
    shots_processed: int = 0


class HealthResponse(BaseModel):
    status: str
    version: str
    services: Dict[str, str]


class ErrorResponse(BaseModel):
    detail: str
    code: Optional[str] = None
