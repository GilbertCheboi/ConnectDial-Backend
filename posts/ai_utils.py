from google import genai
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

def generate_intelligent_caption(news_title, news_desc, league, team=None, personality="hype"):
    """
    Generates unique, personality-driven sports captions using the latest Gemini models.
    Recommended Model: 'gemini-2.5-flash' (Stable 2026) or 'gemini-3-flash'
    """
    
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    
    # Define distinct personas to make the 10,000 bots feel unique
    personality_prompts = {
        "hype": "You are a die-hard super fan. Use caps, be extremely positive, and say things like 'LETS GOOO' or 'WE ARE SO BACK'.",
        "toxic": "You are a salty rival fan. Be critical, use 'L', 'Ratioed', and 'Finished club'.",
        "analytical": "You are a sports tactical nerd. Mention 'expected goals', 'defensive rotations', or 'ball knowledge'.",
        "funny": "You are a meme account. Use sarcasm, dry wit, and references to famous sports memes."
    }

    selected_tone = personality_prompts.get(personality, personality_prompts['hype'])

    prompt = f"""
    Role: {selected_tone}
    
    Context:
    League: {league}
    Focus Team: {team if team else 'General News'}
    News Article: {news_title} - {news_desc}
    
    Instructions:
    Write a social media post (max 200 characters) reacting to this. 
    Stay strictly in character. Use exactly 2 emojis. Do not use hashtags.
    """

    # Try the most stable model for 2026 first
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash', 
            contents=prompt
        )
        return response.text.strip()
    
    except Exception as e:
        logger.warning(f"Gemini 2.5 failed, attempting Gemini 3: {e}")
        try:
            # Fallback to Gemini 3 if 2.5 is restricted/busy
            response = client.models.generate_content(
                model='gemini-3-flash', 
                contents=prompt
            )
            return response.text.strip()
        except Exception as e_final:
            logger.error(f"All LLM models failed: {e_final}")
            # Safe hardcoded fallback so the bot still posts something
            return f"Unreal scenes in the {league}! {news_title} 🤯🔥"