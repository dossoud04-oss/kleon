"""
Video generation with Fallback system:
1. Magic Hour (primary)
2. Agnes AI (secondary)
3. Local FFmpeg image-to-video (last resort free fallback)
"""
import asyncio
import logging
import os
from pathlib import Path
from typing import Optional, Dict, Any
import httpx
import aiofiles
from app.core.config import settings

logger = logging.getLogger(__name__)


async def generate_video_from_image(
    image_path: str,
    prompt: str,
    output_path: str,
    duration_seconds: float = 3.0,
    character_description: Optional[str] = None,
) -> str:
    """
    Generate a short video from a keyframe image + prompt.
    Tries providers in order and falls back to FFmpeg still-to-video.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # 1. Try Magic Hour
    if settings.magic_hour_api_key:
        try:
            result = await _magic_hour_generate(image_path, prompt, output_path, duration_seconds)
            if result:
                return result
        except Exception as e:
            logger.warning(f"Magic Hour failed: {e}")

    # 2. Try Agnes AI
    if settings.agnes_ai_api_key:
        try:
            result = await _agnes_ai_generate(image_path, prompt, output_path, duration_seconds)
            if result:
                return result
        except Exception as e:
            logger.warning(f"Agnes AI failed: {e}")

    # 3. Free local fallback with FFmpeg (ken burns / zoom effect)
    logger.info("Using FFmpeg local image-to-video fallback")
    return await _ffmpeg_image_to_video(image_path, output_path, duration_seconds)


async def _magic_hour_generate(
    image_path: str,
    prompt: str,
    output_path: str,
    duration: float,
) -> Optional[str]:
    """
    Magic Hour image-to-video endpoint (structure based on typical API patterns).
    Adjust endpoint if official docs differ.
    """
    url = f"{settings.magic_hour_base_url}/image-to-video"
    headers = {
        "Authorization": f"Bearer {settings.magic_hour_api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=180.0) as client:
        # Upload image first if required, or send base64 / URL.
        # Many providers accept image URL or multipart.
        # Here we send multipart for robustness.
        with open(image_path, "rb") as f:
            files = {"image": (os.path.basename(image_path), f, "image/jpeg")}
            data = {
                "prompt": prompt[:1000],
                "duration": str(duration),
                "aspect_ratio": "16:9",
            }
            resp = await client.post(url, headers={"Authorization": headers["Authorization"]}, files=files, data=data)

        if resp.status_code not in (200, 201, 202):
            logger.error(f"Magic Hour status {resp.status_code}: {resp.text[:300]}")
            return None

        body = resp.json()
        video_url = body.get("video_url") or body.get("url") or body.get("output", {}).get("url")
        if not video_url:
            # Polling style
            job_id = body.get("id") or body.get("job_id")
            if job_id:
                video_url = await _poll_job(client, f"{settings.magic_hour_base_url}/jobs/{job_id}", headers)
            else:
                return None

        if video_url:
            await _download_file(video_url, output_path)
            return output_path
    return None


async def _agnes_ai_generate(
    image_path: str,
    prompt: str,
    output_path: str,
    duration: float,
) -> Optional[str]:
    """Agnes AI fallback provider."""
    url = f"{settings.agnes_ai_base_url}/generate/video"
    headers = {
        "Authorization": f"Bearer {settings.agnes_ai_api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=180.0) as client:
        with open(image_path, "rb") as f:
            files = {"image": (os.path.basename(image_path), f, "image/jpeg")}
            data = {
                "prompt": prompt[:1000],
                "duration_seconds": str(duration),
                "model": "agnes-video-v1",
            }
            resp = await client.post(url, headers={"Authorization": headers["Authorization"]}, files=files, data=data)

        if resp.status_code not in (200, 201, 202):
            logger.error(f"Agnes AI status {resp.status_code}: {resp.text[:300]}")
            return None

        body = resp.json()
        video_url = body.get("video_url") or body.get("url")
        if video_url:
            await _download_file(video_url, output_path)
            return output_path
    return None


async def _poll_job(client: httpx.AsyncClient, job_url: str, headers: dict, max_attempts: int = 30) -> Optional[str]:
    for _ in range(max_attempts):
        await asyncio.sleep(3)
        r = await client.get(job_url, headers=headers)
        if r.status_code != 200:
            continue
        data = r.json()
        status = data.get("status", "")
        if status in ("completed", "succeeded", "done"):
            return data.get("video_url") or data.get("output", {}).get("url")
        if status in ("failed", "error"):
            return None
    return None


async def _download_file(url: str, dest: str) -> None:
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.get(url, follow_redirects=True)
        resp.raise_for_status()
        async with aiofiles.open(dest, "wb") as f:
            await f.write(resp.content)


async def _ffmpeg_image_to_video(
    image_path: str,
    output_path: str,
    duration: float = 3.0,
) -> str:
    """
    Local free fallback: create a short video from a still image with a subtle zoom (Ken Burns).
    Requires ffmpeg installed on the system.
    """
    import subprocess
    import shlex

    # Ensure even dimensions and good quality
    # Zoompan filter for gentle movement
    # fps=24, duration controlled by frames
    frames = max(24, int(duration * 24))
    filter_complex = (
        f"scale=1280:720:force_original_aspect_ratio=decrease,"
        f"pad=1280:720:(ow-iw)/2:(oh-ih)/2,"
        f"zoompan=z='min(zoom+0.0015,1.15)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1280x720:fps=24"
    )

    cmd = [
        settings.ffmpeg_path,
        "-y",
        "-loop", "1",
        "-i", image_path,
        "-vf", filter_complex,
        "-c:v", "libx264",
        "-t", str(duration),
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-crf", "23",
        output_path,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error(f"FFmpeg error: {stderr.decode()[:500]}")
            # Ultra simple fallback without zoom
            cmd_simple = [
                settings.ffmpeg_path, "-y",
                "-loop", "1", "-i", image_path,
                "-c:v", "libx264", "-t", str(duration),
                "-pix_fmt", "yuv420p", "-vf", "scale=1280:720",
                output_path,
            ]
            proc2 = await asyncio.create_subprocess_exec(*cmd_simple)
            await proc2.communicate()
        return output_path
    except FileNotFoundError:
        logger.error("ffmpeg binary not found. Install ffmpeg.")
        raise RuntimeError("ffmpeg not installed on the server")
