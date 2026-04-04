import random
import requests
import time
from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.utils import timezone

from .models import Post, PostLike, Comment, Hashtag
from leagues.models import League
from .ai_utils import generate_intelligent_caption

User = get_user_model()

# --- 1. CONTENT GENERATION TASKS ---

@shared_task(name="posts.tasks.sync_bots_with_live_sports")
def sync_bots_with_live_sports(league_name, bot_count=3):
    """
    Fetches latest news via NewsAPI and has league-specific bots create posts.
    """
    league = League.objects.filter(name__icontains=league_name).first()
    if not league:
        return f"Skip: {league_name} not found in DB."

    query = f"{league_name} sports highlights"
    news_url = f"https://newsapi.org/v2/everything?q={query}&sortBy=publishedAt&language=en&apiKey={settings.NEWS_API_KEY}"
    
    try:
        response = requests.get(news_url, timeout=10).json()
        articles = response.get('articles', [])
        if not articles:
            return f"No news for {league_name}"
        article = random.choice(articles[:5]) 
    except Exception as e:
        return f"API Error for {league_name}: {str(e)}"

    # CRITICAL FIX: Only select bots that actually have this as their favorite league.
    # Removed the fallback to ensure F1 bots don't post about Premier League.
    bots = User.objects.filter(
        profile__is_bot=True, 
        favorite_league=league
    ).order_by('?')[:bot_count]
    
    if not bots.exists():
        return f"Skip: No specific bots found for {league_name}. Keeping personas consistent."

    for bot in bots:
        # Rate limit protection for Gemini API
        time.sleep(2) 
        
        personality = random.choice(['hype', 'toxic', 'analytical', 'funny'])
        
        caption = generate_intelligent_caption(
            news_title=article['title'],
            news_desc=article.get('description', ''),
            league=league.name,
            team=bot.favorite_team.name if bot.favorite_team else None,
            personality=personality
        )

        post = Post.objects.create(
            author=bot,
            content=caption,
            post_type='image' if article.get('urlToImage') else 'text',
            league=league,
            team=bot.favorite_team
        )

        image_url = article.get('urlToImage')
        if image_url:
            try:
                img_res = requests.get(image_url, timeout=5)
                if img_res.status_code == 200:
                    post.media_file.save(f"bot_{post.id}.jpg", ContentFile(img_res.content), save=True)
            except Exception:
                pass

    return f"Leagues Processed: {league_name} ({len(bots)} bots posted)"


@shared_task(name="posts.tasks.fetch_and_post_youtube_shorts")
def fetch_and_post_youtube_shorts(league_name):
    """
    Finds real broadcast highlights on YouTube and posts them.
    """
    API_KEY = settings.YOUTUBE_API_KEY
    league = League.objects.filter(name__icontains=league_name).first()
    if not league: 
        return f"League {league_name} not found."

    # CRITICAL FIX: Ensure we pick a bot that actually likes this league
    bot_user = User.objects.filter(
        profile__is_bot=True, 
        favorite_league=league
    ).order_by('?').first()
    
    if not bot_user:
        return f"Skip: No {league_name} bot found for Shorts."
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        
    query = f"{league_name} official highlights"                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     
    # CHANGE: videoDuration='any' because official clips often exceed 60 seconds
    url = (
        f"https://www.googleapis.com/youtube/v3/search?part=snippet"
        f"&q={query}&type=video&videoDuration=any&maxResults=10"
        f"&key={API_KEY}"
    )

    try:
        res = requests.get(url, timeout=15).json()
        items = res.get('items', [])
        if not items: 
            return f"No YouTube clips found for {league_name}."

        video_data = random.choice(items)
        video_id = video_data['id']['videoId']
        video_url = f"https://www.youtube.com/watch?v={video_id}"

        # Rate limit protection
        time.sleep(2)

        ai_caption = generate_intelligent_caption(
            news_title=video_data['snippet']['title'],
            news_desc="Broadcast highlight",
            league=league.name,
            personality=random.choice(['hype', 'funny', 'analytical'])
        )

        new_post = Post.objects.create(
            author=bot_user,
            content=f"{ai_caption}\n\n{video_url}",
            post_type='video',
            league=league,
            team=bot_user.favorite_team,
            is_short=True
        )

        for t in [league.name.replace(" ", ""), "Highlights", "ConnectDial"]:
            tag_obj, _ = Hashtag.objects.get_or_create(name=t)
            new_post.hashtags.add(tag_obj)

        return f"📺 YouTube Short: @{bot_user.username} shared {video_id}"
    except Exception as e:
        return f"YouTube API Error: {str(e)}"

# --- 2. SOCIAL INTERACTION TASKS ---

@shared_task(name="posts.tasks.coordinate_bot_engagement")
def coordinate_bot_engagement():
    recent_posts = Post.objects.filter(
        created_at__gte=timezone.now() - timezone.timedelta(minutes=60)
    ).select_related('league', 'author')

    for post in recent_posts:
        delay = 12 * 3600  # 12 hours in seconds
        perform_single_post_engagement.apply_async(args=[post.id], countdown=delay)

    return f"Coordinated engagement for {recent_posts.count()} posts."


@shared_task(name="posts.tasks.perform_single_post_engagement")
def perform_single_post_engagement(post_id):
    try:
        post = Post.objects.get(id=post_id)
        # Bots only engage with posts in their favorite league
        eligible_bots = User.objects.filter(
            profile__is_bot=True,
            favorite_league=post.league
        ).exclude(id=post.author.id)

        if not eligible_bots.exists():
            return f"No matching bots for post {post_id} league."

        participants = eligible_bots.order_by('?')[:random.randint(1, 2)]

        for bot in participants:
            action = random.choice(['like', 'comment', 'repost'])
            if action == 'like':
                PostLike.objects.get_or_create(user=bot, post=post)
            elif action == 'comment':
                time.sleep(2)
                ai_comment = generate_intelligent_caption(
                    news_title=post.content[:100],
                    news_desc="User generated post",
                    league=post.league.name if post.league else "Sports",
                    personality=random.choice(['hype', 'funny', 'analytical'])
                )
                Comment.objects.create(user=bot, post=post, content=ai_comment)
            elif action == 'repost':
                Post.objects.create(
                    author=bot,
                    content=f"Check this out! #{post.league.name.replace(' ', '') if post.league else 'Sports'}",
                    post_type='text',
                    league=post.league,
                    parent_post=post,
                    is_repost=True
                )
        return f"Engaged with Post {post_id}"
    except Post.DoesNotExist:
        return "Post not found."


@shared_task(name="posts.tasks.expand_bot_social_graph")
def expand_bot_social_graph(batch_size=10):
    from users.models import Follow 
    
    bots = User.objects.filter(profile__is_bot=True).order_by('?')[:batch_size]

    for bot in bots:
        potential_targets = User.objects.filter(
            favorite_league=bot.favorite_league
        ).exclude(id=bot.id).exclude(
            followers__follower=bot 
        ).order_by('profile__is_bot', '?') 

        target = potential_targets.first()
        if target:
            Follow.objects.get_or_create(follower=bot, followed=target)
            
    return f"Social graph expanded for {len(bots)} bots."