import re
from datetime import timedelta
from django.utils import timezone
from django.db.models import Count
from django.contrib.auth import get_user_model
from .models import Hashtag




import re
from django.contrib.auth import get_user_model
from notifications.models import Notification

User = get_user_model()


def extract_urls(text):
    """
    Finds all URLs starting with http or https.
    """
    if not text:
        return set()
    # Comprehensive URL regex
    url_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    return set(re.findall(url_pattern, text))

def process_post_metadata(post_instance):
    """
    The definitive 'ConnectDial' metadata processor.
    Handles Mentions, Hashtags, and Link detection in one pass.
    """
    content = post_instance.content
    if not content:
        # Clear existing relationships if content is deleted
        post_instance.mentions.clear()
        post_instance.hashtags.clear()
        return

    # 1. Handle Mentions (@username)
    mention_names = set(re.findall(r'@(\w+)', content))
    if mention_names:
        User = get_user_model()
        users = User.objects.filter(username__in=mention_names)
        post_instance.mentions.set(users)
    else:
        post_instance.mentions.clear()

    # 2. Handle Hashtags (#topic)
    hashtag_names = set(re.findall(r'#(\w+)', content))
    if hashtag_names:
        hashtag_objs = [
            Hashtag.objects.get_or_create(name=name.lower())[0] 
            for name in hashtag_names
        ]
        post_instance.hashtags.set(hashtag_objs)
    else:
        post_instance.hashtags.clear()

    # 3. Handle Links (URLs)
    links = extract_urls(content)
    if links:
        # Log links for now. 
        # Future: Trigger a Celery task here to generate link previews.
        print(f"Post {post_instance.id} contains links: {links}")


def get_trending_hashtags(limit=10, days=1):
    """
    Business logic for the Trending Feed.
    """
    time_threshold = timezone.now() - timedelta(days=days)
    
    return Hashtag.objects.filter(
        posts__created_at__gte=time_threshold
    ).annotate(
        post_count=Count('posts')
    ).order_by('-post_count')[:limit]

def handle_mentions(post_instance):
    """
    Scans post content for @username and creates notifications.
    """
    if not post_instance.content:
        return

    # Regex to find @usernames (alphanumeric and underscores)
    mentions = re.findall(r'@(\w+)', post_instance.content)
    
    # Get unique usernames, excluding the author themselves
    unique_mentions = set(m for m in mentions if m != post_instance.author.username)

    for username in unique_mentions:
        try:
            mentioned_user = User.objects.get(username__iexact=username)
            Notification.objects.get_or_create(
                recipient=mentioned_user,
                sender=post_instance.author,
                notification_type='mention',
                post=post_instance
            )
        except User.DoesNotExist:
            continue