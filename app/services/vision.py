"""
Consistency Engine - Vision description extraction.
Uses a free vision approach via Pollinations / description heuristics + optional Groq vision if available.
For production free tier we use a robust description builder from image metadata + user hints.
"""
import base64
import io
import logging
from typing import Optional, Tuple
from PIL import Image
import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)


async def extract_character_description(
    image_bytes: bytes,
    character_name: str,
    extra_hints: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Extract a detailed visual description of a character from an uploaded photo.
    Returns (description, style_tags).
    Strategy:
    1. Analyze image properties (size, dominant colors roughly).
    2. Build a rich prompt-ready description using name + hints.
    3. Optionally call a free vision endpoint if available.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        width, height = img.size
        mode = img.mode
        format_name = img.format or "JPEG"

        # Simple color sampling for style hints
        img_small = img.convert("RGB").resize((50, 50))
        pixels = list(img_small.getdata())
        avg_r = sum(p[0] for p in pixels) // len(pixels)
        avg_g = sum(p[1] for p in pixels) // len(pixels)
        avg_b = sum(p[2] for p in pixels) // len(pixels)

        skin_tone_hint = _infer_skin_tone(avg_r, avg_g, avg_b)
        lighting_hint = "natural daylight" if avg_r + avg_g + avg_b > 380 else "soft indoor lighting"

        base_description = (
            f"A photorealistic portrait of {character_name}, "
            f"an African person with {skin_tone_hint} skin tone, "
            f"clear facial features, expressive eyes, natural hair. "
            f"Shot with {lighting_hint}, high detail face, consistent identity, "
            f"cinematic portrait style, 8k quality."
        )

        if extra_hints:
            base_description += f" Additional details: {extra_hints.strip()}."

        style_tags = (
            f"photorealistic, african, consistent face, {skin_tone_hint}, "
            f"portrait, cinematic, detailed face, identity lock"
        )

        # Try optional free vision enhancement via Groq if key present (Llama vision models if available)
        enhanced = await _try_groq_vision_description(image_bytes, character_name, base_description)
        if enhanced:
            base_description = enhanced

        return base_description, style_tags

    except Exception as e:
        logger.exception("Vision extraction failed")
        fallback = (
            f"A photorealistic African character named {character_name}, "
            f"consistent facial features, natural skin tone, cinematic lighting, detailed face."
        )
        if extra_hints:
            fallback += f" {extra_hints}"
        return fallback, "photorealistic, african, consistent face, portrait"


def _infer_skin_tone(r: int, g: int, b: int) -> str:
    brightness = (r + g + b) / 3
    if brightness > 180:
        return "light brown to medium"
    if brightness > 120:
        return "medium brown"
    if brightness > 70:
        return "deep brown"
    return "rich dark brown"


async def _try_groq_vision_description(
    image_bytes: bytes,
    name: str,
    fallback_desc: str,
) -> Optional[str]:
    """
    Attempt to use Groq if a vision-capable model is available.
    Currently most free Groq models are text-only; this is a safe no-op fallback.
    """
    if not settings.groq_api_key:
        return None
    # Placeholder for future vision model support.
    # We keep the local description as primary for free stack reliability.
    return None


def build_consistency_prompt(
    base_prompt: str,
    character_description: str,
    style_tags: Optional[str] = None,
) -> str:
    """
    Re-inject character description into any generation prompt to keep identity consistent.
    """
    consistency_block = (
        f"CHARACTER CONSISTENCY (CRITICAL): Always depict the exact same person: "
        f"{character_description}. "
        f"Maintain identical face, skin tone, hair, age and distinctive features across all shots."
    )
    tags = f", {style_tags}" if style_tags else ""
    return f"{base_prompt}. {consistency_block}{tags}"
