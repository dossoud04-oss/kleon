"""
Storyboard Generator
Uses Groq (Llama 3.3) to split a script into cinematic shots with visual prompts.
"""
import json
import logging
import re
from typing import List, Dict, Any, Optional
from groq import Groq
from app.core.config import settings
from app.services.local_context import enrich_prompt_with_local_context, get_template_by_id
from app.services.vision import build_consistency_prompt

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """Tu es un réalisateur publicitaire expert spécialisé dans les publicités vidéo courtes pour le marché africain francophone.
Ton rôle est de découper un script publicitaire en plans cinématographiques clairs et réalisables.

Règles STRICTES :
1. Réponds UNIQUEMENT avec un JSON valide, sans markdown, sans texte avant ou après.
2. Structure exacte :
{
  "shots": [
    {
      "shot_number": 1,
      "description": "Description narrative courte du plan en français",
      "visual_prompt": "Prompt détaillé en anglais pour génération image/vidéo (sujet, action, cadrage, lumière, ambiance)",
      "duration_seconds": 3.0,
      "camera": "medium shot | close-up | wide shot | tracking | etc.",
      "mood": "energetic | emotional | aspirational | playful | etc."
    }
  ],
  "total_duration_estimate": 25,
  "style_notes": "Notes de style globales"
}
3. Nombre de plans : entre 5 et 12 selon la longueur du script.
4. Chaque visual_prompt doit être auto-suffisant, en anglais, très descriptif, prêt pour un modèle image/vidéo.
5. Respecte le personnage fourni (si présent) pour la cohérence.
6. Intègre le contexte local africain quand fourni.
7. Durées réalistes (2.5s à 5s par plan).
8. Le premier plan est souvent un hook fort, le dernier un call-to-action ou logo moment.
"""


async def generate_storyboard(
    script: str,
    title: str,
    character_description: Optional[str] = None,
    character_style_tags: Optional[str] = None,
    scene_template_id: Optional[str] = None,
    target_duration: int = 30,
    style: str = "cinematic realistic african",
    language: str = "fr",
) -> Dict[str, Any]:
    """
    Call Groq Llama to produce a structured storyboard.
    Falls back to a deterministic splitter if Groq is unavailable.
    """
    if not settings.groq_api_key:
        logger.warning("No GROQ_API_KEY – using fallback storyboard generator")
        return _fallback_storyboard(script, title, character_description, scene_template_id, target_duration, style)

    client = Groq(api_key=settings.groq_api_key)

    user_content = f"""Titre de la pub : {title}
Durée cible : ~{target_duration} secondes
Style global : {style}
Langue du script : {language}

SCRIPT :
\"\"\"
{script}
\"\"\"
"""

    if character_description:
        user_content += f"\n\nPERSONNAGE PRINCIPAL (à garder cohérent) :\n{character_description}\n"
        if character_style_tags:
            user_content += f"Tags de style personnage : {character_style_tags}\n"

    if scene_template_id:
        tpl = get_template_by_id(scene_template_id)
        if tpl:
            user_content += (
                f"\n\nCONTEXTE LOCAL OBLIGATOIRE :\n"
                f"Lieu : {tpl['name']} ({tpl['location']}, {tpl['country']})\n"
                f"Description : {tpl['description']}\n"
                f"Mots-clés visuels : {tpl['visual_keywords']}\n"
            )

    user_content += "\n\nGénère maintenant le JSON du storyboard."

    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.4,
            max_tokens=4096,
            response_format={"type": "json_object"},
        )
        raw = completion.choices[0].message.content
        data = json.loads(raw)

        # Post-process: enrich visual prompts with consistency + local context
        shots = data.get("shots", [])
        for shot in shots:
            vp = shot.get("visual_prompt", "")
            if character_description:
                vp = build_consistency_prompt(vp, character_description, character_style_tags)
            vp = enrich_prompt_with_local_context(vp, scene_template_id)
            # Ensure style is present
            if style and style.lower() not in vp.lower():
                vp = f"{vp}, {style}"
            shot["visual_prompt"] = vp

        data["shots"] = shots
        return data

    except Exception as e:
        logger.exception(f"Groq storyboard generation failed: {e}")
        return _fallback_storyboard(script, title, character_description, scene_template_id, target_duration, style)


def _fallback_storyboard(
    script: str,
    title: str,
    character_description: Optional[str],
    scene_template_id: Optional[str],
    target_duration: int,
    style: str,
) -> Dict[str, Any]:
    """
    Deterministic splitter when LLM is unavailable.
    Splits by sentences / paragraphs into ~6-8 shots.
    """
    # Clean and split
    text = re.sub(r"\s+", " ", script).strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 8]

    if len(sentences) < 3:
        # Force split by length
        words = text.split()
        chunk_size = max(8, len(words) // 6)
        sentences = [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]

    n_shots = min(max(5, len(sentences)), 10)
    duration_per = round(target_duration / n_shots, 1)

    shots = []
    for i in range(n_shots):
        sent = sentences[i % len(sentences)]
        desc = f"Plan {i + 1} : {sent[:120]}"
        visual = (
            f"Cinematic shot of the scene illustrating: {sent[:80]}. "
            f"Professional advertising style, high quality, {style}."
        )
        if character_description:
            visual = build_consistency_prompt(visual, character_description)
        visual = enrich_prompt_with_local_context(visual, scene_template_id)

        shots.append({
            "shot_number": i + 1,
            "description": desc,
            "visual_prompt": visual,
            "duration_seconds": duration_per,
            "camera": "medium shot" if i % 2 == 0 else "close-up",
            "mood": "energetic" if i < 2 else ("aspirational" if i > n_shots - 3 else "engaging"),
        })

    return {
        "shots": shots,
        "total_duration_estimate": target_duration,
        "style_notes": f"Fallback storyboard for '{title}'. Style: {style}",
    }
