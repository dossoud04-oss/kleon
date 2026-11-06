"""
Final video assembly with FFmpeg.
Concatenates all shot videos into one final advertisement.
"""
import asyncio
import logging
import os
from pathlib import Path
from typing import List, Optional
from app.core.config import settings

logger = logging.getLogger(__name__)


async def assemble_final_video(
    shot_video_paths: List[str],
    output_path: str,
    transition: str = "none",
    add_fade: bool = True,
) -> str:
    """
    Concatenate a list of short videos into a single final video.
    """
    if not shot_video_paths:
        raise ValueError("No shot videos to assemble")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Create concat list file
    list_file = output_path + ".txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for p in shot_video_paths:
            # FFmpeg concat demuxer requires absolute or escaped paths
            abs_p = os.path.abspath(p)
            f.write(f"file '{abs_p}'\n")

    # Build filter for optional fades
    # Simple concat first (most reliable)
    cmd = [
        settings.ffmpeg_path,
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", list_file,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output_path,
    ]

    if add_fade:
        # We can add a global fade-in / fade-out after concat if desired
        # For simplicity and reliability we keep a clean concat.
        pass

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error(f"FFmpeg assemble error: {stderr.decode()[:800]}")
            raise RuntimeError(f"FFmpeg failed: {stderr.decode()[:300]}")

        # Cleanup list file
        try:
            os.remove(list_file)
        except OSError:
            pass

        logger.info(f"Final video assembled at {output_path}")
        return output_path

    except FileNotFoundError:
        raise RuntimeError("ffmpeg binary not found. Please install ffmpeg.")


async def add_audio_track(
    video_path: str,
    audio_path: str,
    output_path: str,
    audio_volume: float = 0.8,
) -> str:
    """Optional: mix a background music track (user provided)."""
    cmd = [
        settings.ffmpeg_path, "-y",
        "-i", video_path,
        "-i", audio_path,
        "-filter_complex", f"[1:a]volume={audio_volume}[a]",
        "-map", "0:v",
        "-map", "[a]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        output_path,
    ]
    proc = await asyncio.create_subprocess_exec(*cmd)
    await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError("Failed to add audio track")
    return output_path
