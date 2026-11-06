"""
Local Context Booster
Loads African scene templates and enriches generation prompts with local cultural context.
"""
import json
import os
import logging
from typing import List, Optional, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)

TEMPLATES_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "templates_scenes.json"

_templates_cache: Optional[List[Dict[str, Any]]] = None


def load_templates() -> List[Dict[str, Any]]:
    global _templates_cache
    if _templates_cache is not None:
        return _templates_cache
    try:
        with open(TEMPLATES_PATH, "r", encoding="utf-8") as f:
            _templates_cache = json.load(f)
        logger.info(f"Loaded {len(_templates_cache)} scene templates")
        return _templates_cache
    except Exception as e:
        logger.error(f"Failed to load templates: {e}")
        return []


def get_template_by_id(template_id: str) -> Optional[Dict[str, Any]]:
    templates = load_templates()
    for t in templates:
        if t.get("id") == template_id:
            return t
    return None


def list_templates() -> List[Dict[str, Any]]:
    return load_templates()


def enrich_prompt_with_local_context(
    base_prompt: str,
    template_id: Optional[str] = None,
    extra_context: Optional[str] = None,
) -> str:
    """
    Inject local African context into a visual prompt.
    """
    parts = [base_prompt.strip()]

    if template_id:
        tpl = get_template_by_id(template_id)
        if tpl:
            context_block = (
                f"LOCAL AFRICAN CONTEXT: Setting is {tpl['name']} ({tpl['location']}, {tpl['country']}). "
                f"{tpl['description']} "
                f"Visual keywords to include: {tpl['visual_keywords']}."
            )
            if tpl.get("cultural_notes"):
                context_block += f" Cultural notes: {tpl['cultural_notes']}"
            parts.append(context_block)

    if extra_context:
        parts.append(f"ADDITIONAL LOCAL CONTEXT: {extra_context.strip()}")

    # Always add a light African authenticity boost
    parts.append(
        "Authentic African setting, realistic lighting, culturally respectful depiction, "
        "high detail, cinematic composition."
    )

    return " ".join(parts)


def get_random_template() -> Optional[Dict[str, Any]]:
    import random
    templates = load_templates()
    if not templates:
        return None
    return random.choice(templates)
