"""
tasks.py – ConnectDial Celery tasks
────────────────────────────────────
• sync_bots_with_live_sports      – NewsAPI → AI caption → bot post
• fetch_and_post_youtube_shorts   – YouTube highlights → bot short
• coordinate_bot_engagement       – schedule per-post engagement
• perform_single_post_engagement  – like / comment / repost
• expand_bot_social_graph         – bots follow same-league users
• process_video_upload            – FFmpeg trim + music (server-side)
"""

import os
import random
import tempfile
import time

import requests
from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db.models import F
from django.utils import timezone

from .models import Comment, Hashtag, Post, PostLike, VideoUploadSession
from .ai_utils import generate_intelligent_caption
from leagues.models import League

User = get_user_model()

# ─────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────

def _get_league(league_name: str):
    league = League.objects.filter(name__icontains=league_name).first()
    if not league:
        raise ValueError(f"League '{league_name}' not found in DB.")
    return league


def _safe_get(url: str, timeout: int = 10) -> requests.Response:
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp


# ─────────────────────────────────────────────────────────────────────
# 1. NEWS → BOT POSTS
# ─────────────────────────────────────────────────────────────────────

@shared_task(
    name='posts.tasks.sync_bots_with_live_sports',
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def sync_bots_with_live_sports(self, league_name: str, bot_count: int = 3):
    """
    1. Fetch latest news from NewsAPI for the league.
    2. Pick N league-specific bots.
    3. Generate AI captions and create Posts.
    """
    try:
        league = _get_league(league_name)
    except ValueError as e:
        return str(e)

    url = (
        f"https://newsapi.org/v2/everything"
        f"?q={league_name}+sports+highlights"
        f"&sortBy=publishedAt&language=en"
        f"&apiKey={settings.NEWS_API_KEY}"
    )

    try:
        articles = _safe_get(url).json().get('articles', [])
    except Exception as exc:
        return self.retry(exc=exc)

    if not articles:
        return f"No news for {league_name}"

    article = random.choice(articles[:5])

    bots = list(
        User.objects.filter(
            profile__is_bot=True,
            favorite_league=league,
        ).select_related('favorite_team').order_by('?')[:bot_count]
    )

    if not bots:
        return f"No bots found for {league_name}"

    created = 0
    for bot in bots:
        time.sleep(2)  # respect Gemini rate limit
        personality = random.choice(['hype', 'toxic', 'analytical', 'funny'])
        caption = generate_intelligent_caption(
            news_title=article['title'],
            news_desc=article.get('description', ''),
            league=league.name,
            team=bot.favorite_team.name if bot.favorite_team else None,
            personality=personality,
        )

        post = Post.objects.create(
            author    = bot,
            content   = caption,
            post_type = 'image' if article.get('urlToImage') else 'text',
            league    = league,
            team      = bot.favorite_team,
        )

        image_url = article.get('urlToImage')
        if image_url:
            try:
                img_bytes = _safe_get(image_url, timeout=5).content
                post.media_file.save(f"bot_{post.id}.jpg", ContentFile(img_bytes), save=True)
            except Exception:
                pass

        created += 1

    return f"{league_name}: {created} bot posts created."


# ─────────────────────────────────────────────────────────────────────
# 2. YOUTUBE SHORTS → BOT POSTS
# ─────────────────────────────────────────────────────────────────────

@shared_task(
    name='posts.tasks.fetch_and_post_youtube_shorts',
    bind=True,
    max_retries=2,
    default_retry_delay=120,
)
def fetch_and_post_youtube_shorts(self, league_name: str):
    try:
        league = _get_league(league_name)
    except ValueError as e:
        return str(e)

    bot = (
        User.objects
        .filter(profile__is_bot=True, favorite_league=league)
        .select_related('favorite_team')
        .order_by('?')
        .first()
    )
    if not bot:
        return f"No bot for {league_name}"

    url = (
        f"https://www.googleapis.com/youtube/v3/search"
        f"?part=snippet&q={league_name}+official+highlights"
        f"&type=video&videoDuration=any&maxResults=10"
        f"&key={settings.YOUTUBE_API_KEY}"
    )

    try:
        items = _safe_get(url, timeout=15).json().get('items', [])
    except Exception as exc:
        return self.retry(exc=exc)

    if not items:
        return f"No YouTube clips for {league_name}"

    item       = random.choice(items)
    video_id   = item['id']['videoId']
    video_url  = f"https://www.youtube.com/watch?v={video_id}"

    time.sleep(2)
    caption = generate_intelligent_caption(
        news_title=item['snippet']['title'],
        news_desc='Broadcast highlight',
        league=league.name,
        personality=random.choice(['hype', 'funny', 'analytical']),
    )

    post = Post.objects.create(
        author    = bot,
        content   = f"{caption}\n\n{video_url}",
        post_type = 'video',
        league    = league,
        team      = bot.favorite_team,
        is_short  = True,
    )

    for tag_name in [league.name.replace(' ', ''), 'Highlights', 'ConnectDial']:
        tag, _ = Hashtag.objects.get_or_create(name=tag_name.lower())
        post.hashtags.add(tag)

    return f"@{bot.username} posted YouTube short {video_id}"


# ─────────────────────────────────────────────────────────────────────
# 3. COORDINATE BOT ENGAGEMENT
# ─────────────────────────────────────────────────────────────────────

@shared_task(name='posts.tasks.coordinate_bot_engagement')
def coordinate_bot_engagement():
    """
    Finds recent posts and schedules delayed engagement for realism.
    """
    cutoff = timezone.now() - timezone.timedelta(hours=1)
    post_ids = list(
        Post.objects
        .filter(created_at__gte=cutoff)
        .values_list('id', flat=True)
    )
    for pid in post_ids:
        perform_single_post_engagement.apply_async(
            args=[pid],
            countdown=random.randint(300, 43200),  # 5 min – 12 hours
        )
    return f"Scheduled engagement for {len(post_ids)} posts."


# ─────────────────────────────────────────────────────────────────────
# 4. SINGLE-POST BOT ENGAGEMENT
# ─────────────────────────────────────────────────────────────────────

@shared_task(name='posts.tasks.perform_single_post_engagement')
def perform_single_post_engagement(post_id: int):
    try:
        post = Post.objects.select_related('league', 'author').get(id=post_id)
    except Post.DoesNotExist:
        return f"Post {post_id} not found."

    eligible = list(
        User.objects.filter(
            profile__is_bot=True,
            favorite_league=post.league,
        )
        .exclude(id=post.author_id)
        .select_related('favorite_team')
        .order_by('?')[:random.randint(1, 3)]
    )

    if not eligible:
        return f"No bots for post {post_id}."

    for bot in eligible:
        action = random.choice(['like', 'comment', 'repost'])

        if action == 'like':
            _, created = PostLike.objects.get_or_create(user=bot, post=post)
            if created:
                post.increment_like()

        elif action == 'comment':
            time.sleep(2)
            ai_comment = generate_intelligent_caption(
                news_title=post.content[:100],
                news_desc='User generated post',
                league=post.league.name if post.league else 'Sports',
                personality=random.choice(['hype', 'funny', 'analytical']),
            )
            Comment.objects.create(user=bot, post=post, content=ai_comment)
            post.increment_comment()

        elif action == 'repost':
            league_tag = post.league.name.replace(' ', '') if post.league else 'Sports'
            Post.objects.create(
                author      = bot,
                content     = f"Check this out! #{league_tag}",
                post_type   = 'text',
                league      = post.league,
                parent_post = post,
                is_repost   = True,
            )

    return f"Engaged with post {post_id} ({len(eligible)} bots)"


# ─────────────────────────────────────────────────────────────────────
# 5. EXPAND BOT SOCIAL GRAPH
# ─────────────────────────────────────────────────────────────────────

@shared_task(name='posts.tasks.expand_bot_social_graph')
def expand_bot_social_graph(batch_size: int = 10):
    from users.models import Follow

    bots = list(
        User.objects
        .filter(profile__is_bot=True)
        .select_related('favorite_league')
        .order_by('?')[:batch_size]
    )

    followed = 0
    for bot in bots:
        target = (
            User.objects
            .filter(favorite_league=bot.favorite_league)
            .exclude(id=bot.id)
            .exclude(followers__follower=bot)
            .order_by('profile__is_bot', '?')
            .first()
        )
        if target:
            Follow.objects.get_or_create(follower=bot, followed=target)
            followed += 1

    return f"Social graph expanded: {followed} new follows."


# ─────────────────────────────────────────────────────────────────────
# 6. VIDEO PROCESSING  (FFmpeg)
# ─────────────────────────────────────────────────────────────────────

@shared_task(
    name='posts.tasks.process_video_upload',
    bind=True,
    max_retries=1,
)
def process_video_upload(self, post_id: int, song_id=None, trim_range=(0, None), upload_id=None):
    """
    1. Assemble temp chunks into a single file.
    2. Run FFmpeg trim + (optional) audio overlay.
    3. Save to Post.media_file and mark video_status='ready'.
    """
    import subprocess
    from django.core.files import File

    try:
        post = Post.objects.get(id=post_id)
    except Post.DoesNotExist:
        return f"Post {post_id} not found."

    tmp_dir    = os.path.join(tempfile.gettempdir(), str(upload_id or post_id))
    raw_path   = os.path.join(tmp_dir, 'assembled.mp4')
    output_path = os.path.join(tmp_dir, 'output.mp4')

    try:
        # ── Assemble chunks ──────────────────────────────────────────
        chunk_files = sorted(
            [f for f in os.listdir(tmp_dir) if f.startswith('chunk_')]
        )
        with open(raw_path, 'wb') as outfile:
            for chunk_name in chunk_files:
                with open(os.path.join(tmp_dir, chunk_name), 'rb') as cf:
                    outfile.write(cf.read())

        # ── Build FFmpeg command ─────────────────────────────────────
        trim_start = trim_range[0] or 0
        trim_end   = trim_range[1]

        vf_filters = 'scale=720:-2'  # 720p for mobile
        cmd = ['ffmpeg', '-y', '-i', raw_path]

        if trim_start:
            cmd += ['-ss', str(trim_start)]
        if trim_end:
            cmd += ['-to', str(trim_end)]

        if song_id:
            # Future: resolve song path from DB
            # song_path = Song.objects.get(id=song_id).file.path
            # cmd += ['-i', song_path, '-map', '0:v', '-map', '1:a', '-shortest']
            pass

        cmd += [
            '-vf', vf_filters,
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-crf', '28',
            '-movflags', '+faststart',  # enables streaming before full download
            '-c:a', 'aac',
            '-b:a', '128k',
            output_path,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {result.stderr}")

        # ── Save to Django media storage ─────────────────────────────
        with open(output_path, 'rb') as f:
            post.media_file.save(f"video_{post_id}.mp4", File(f), save=False)

        Post.objects.filter(pk=post_id).update(
            video_status='ready',
            media_file=post.media_file.name,
        )

    except Exception as exc:
        Post.objects.filter(pk=post_id).update(video_status='failed')
        raise self.retry(exc=exc)

    finally:
        # Cleanup temp files
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return f"Video {post_id} processed successfully."
