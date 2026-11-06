"""
Image generation via Pollinations.ai (free, no API key required).
"""
import hashlib
import logging
import os
from pathlib import Path
from typing import Optional
from urllib.parse import quote
import httpx
import aiofiles
from app.core.config import settings

logger = logging.getLogger(__name__)


async def generate_image(
    prompt: str,
    output_path: str,
    width: int = 1024,
    height: int = 576,
    seed: Optional[int] = None,
    model: str = "flux",
) -> str:
    """
    Generate an image using Pollinations.ai and save it to disk.
    Returns the local file path.
    """
    # Clean prompt for URL
    clean_prompt = prompt.strip()[:1200]  # Keep reasonable length
    encoded = quote(clean_prompt)

    # Build URL
    # https://image.pollinations.ai/prompt/{prompt}?width=...&height=...&seed=...&model=...
    params = f"width={width}&height={height}&nologo=true&enhance=true"
    if seed is not None:
        params += f"&seed={seed}"
    if model:
        params += f"&model={model}"

    url = f"{settings.pollinations_base_url}/{encoded}?{params}"

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
            content = resp.content

            if len(content) < 1000:
                raise ValueError("Received too small image data from Pollinations")

            async with aiofiles.open(output_path, "wb") as f:
                await f.write(content)

        logger.info(f"Image saved to {output_path}")
        return output_path

    except Exception as e:
        logger.exception(f"Pollinations image generation failed: {e}")
        # Create a simple placeholder so pipeline can continue
        return await _create_placeholder(output_path, prompt)


async def _create_placeholder(output_path: str, prompt: str) -> str:
    """Generate a minimal placeholder image with Pillow if remote fails."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1024, 576), color=(30, 30, 50))
    draw = ImageDraw.Draw(img)
    text = "Kleos Placeholder\n" + (prompt[:80] + "..." if len(prompt) > 80 else prompt)
    try:
        draw.text((40, 250), text, fill=(200, 200, 220))
    except Exception:
        pass
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "JPEG", quality=85)
    return output_path


def make_seed_from_text(text: str) -> int:
    """Deterministic seed for consistency across regenerations."""
    h = hashlib.md5(text.encode("utf-8")).hexdigest()
    return int(h[:8], 16) % 999999
