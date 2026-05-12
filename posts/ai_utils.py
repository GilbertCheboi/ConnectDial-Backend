"""
ai_utils.py – Gemini AI caption generator for ConnectDial bots
──────────────────────────────────────────────────────────────
Uses google-genai SDK (pip install google-genai).
Falls back through model versions gracefully.
"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)

# Ordered list of models to try (most capable → fastest)
_MODEL_PRIORITY = [
    'gemini-2.5-flash',
    'gemini-2.0-flash',
    'gemini-1.5-flash',
]

_PERSONALITIES = {
    'hype': (
        "You are a die-hard super fan. Use caps, be extremely positive. "
        "Say things like 'LETS GOOO' or 'WE ARE SO BACK'."
    ),
    'toxic': (
        "You are a salty rival fan. Be critical, use 'L', 'Ratioed', "
        "and 'Finished club'."
    ),
    'analytical': (
        "You are a sports tactical nerd. Mention 'expected goals', "
        "'defensive rotations', or 'ball knowledge'."
    ),
    'funny': (
        "You are a meme account. Use sarcasm, dry wit, and references "
        "to famous sports memes."
    ),
}

_FALLBACK_CAPTION = "Unreal scenes in the {league}! {title} 🤯🔥"


def generate_intelligent_caption(
    news_title: str,
    news_desc: str,
    league: str,
    team: str = None,
    personality: str = 'hype',
) -> str:
    """
    Generates a personality-driven sports caption via Gemini.

    Tries models in _MODEL_PRIORITY order and returns a hardcoded
    fallback string if all fail, so bots always post something.
    """
    try:
        from google import genai  # lazy import – not needed for non-AI paths
    except ImportError:
        logger.error("google-genai package not installed (pip install google-genai)")
        return _FALLBACK_CAPTION.format(league=league, title=news_title[:60])

    tone = _PERSONALITIES.get(personality, _PERSONALITIES['hype'])

    prompt = (
        f"Role: {tone}\n\n"
        f"Context:\n"
        f"League: {league}\n"
        f"Focus Team: {team or 'General News'}\n"
        f"News: {news_title} – {news_desc}\n\n"
        f"Instructions:\n"
        f"Write a social media post (max 200 characters) reacting to this news. "
        f"Stay strictly in character. Use exactly 2 emojis. Do not use hashtags."
    )

    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    for model in _MODEL_PRIORITY:
        try:
            response = client.models.generate_content(model=model, contents=prompt)
            text = response.text.strip()
            if text:
                logger.debug("Caption generated via %s", model)
                return text[:220]  # hard cap so DB field never overflows
        except Exception as exc:
            logger.warning("Model %s failed: %s", model, exc)
            continue

    logger.error("All Gemini models failed for league=%s", league)
    return _FALLBACK_CAPTION.format(league=league, title=news_title[:60])
