"""
services.py – ConnectDial core business logic
─────────────────────────────────────────────
• process_post_metadata  – hashtags + mentions in one DB round-trip
• handle_mentions        – @mention notifications (deduped)
• get_trending_hashtags  – Redis-cached trending feed
• get_personalized_shorts – pure-SQL hot-score ranking
• get_home_feed_queryset  – optimised home feed (no N+1)
"""

import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db.models import (
    Count, ExpressionWrapper, F, FloatField,
    OuterRef, Subquery, Value, Case, When,
)
from django.db.models.functions import ExtractDay, ExtractHour, Now
from django.utils import timezone

from .models import Hashtag, Post, PostLike

User = get_user_model()

# ─────────────────────────────────────────────────────────────────────
# Regex constants compiled once at import time
# ─────────────────────────────────────────────────────────────────────
_RE_MENTION  = re.compile(r'@(\w+)')
_RE_HASHTAG  = re.compile(r'#(\w+)')
_RE_URL      = re.compile(
    r'http[s]?://(?:[a-zA-Z0-9$\-_.+!*\'(),]|(?:%[0-9a-fA-F]{2}))+'
)

# ─────────────────────────────────────────────────────────────────────
# 1. METADATA PROCESSOR
# ─────────────────────────────────────────────────────────────────────

def extract_urls(text: str) -> set:
    if not text:
        return set()
    return set(_RE_URL.findall(text))


def process_post_metadata(post_instance):
    """
    Single-pass extractor for @mentions, #hashtags and URLs.
    Runs on every save (new post + edit) so data stays in sync.
    Uses bulk get_or_create to minimise DB round-trips.
    """
    content = post_instance.content or ''

    # ── Mentions ──────────────────────────────────────────────────────
    mention_names = {m.lower() for m in _RE_MENTION.findall(content)}
    if mention_names:
        users = User.objects.filter(username__iexact_in=mention_names) \
            if hasattr(User.objects, 'iexact_in') \
            else User.objects.filter(username__in=mention_names)
        post_instance.mentions.set(users)
    else:
        post_instance.mentions.clear()

    # ── Hashtags ──────────────────────────────────────────────────────
    hashtag_names = {h.lower() for h in _RE_HASHTAG.findall(content)}
    if hashtag_names:
        # Fetch existing in one query, create missing ones in bulk
        existing = {h.name: h for h in Hashtag.objects.filter(name__in=hashtag_names)}
        to_create = [Hashtag(name=n) for n in hashtag_names if n not in existing]
        if to_create:
            Hashtag.objects.bulk_create(to_create, ignore_conflicts=True)
            # Re-fetch so we have all PKs
            existing = {h.name: h for h in Hashtag.objects.filter(name__in=hashtag_names)}
        post_instance.hashtags.set(existing.values())
    else:
        post_instance.hashtags.clear()

    # ── URLs ──────────────────────────────────────────────────────────
    links = extract_urls(content)
    if links:
        # Future: trigger async Celery task for link-preview generation
        # tasks.generate_link_preview.delay(post_instance.id, list(links))
        pass


# ─────────────────────────────────────────────────────────────────────
# 2. MENTION NOTIFICATIONS
# ─────────────────────────────────────────────────────────────────────

def handle_mentions(post_instance):
    """
    Creates a Notification for every unique @mention,
    excluding the author themselves.  Uses get_or_create to
    avoid duplicate notifications on re-saves.
    """
    from notifications.models import Notification  # local import to avoid circular

    content = post_instance.content or ''
    usernames = {
        m for m in _RE_MENTION.findall(content)
        if m.lower() != post_instance.author.username.lower()
    }
    if not usernames:
        return

    users = User.objects.filter(username__in=usernames).only('id')
    notifications = [
        Notification(
            recipient=u,
            sender=post_instance.author,
            notification_type='mention',
            post=post_instance,
        )
        for u in users
    ]
    # Bulk-create; duplicates are silently ignored via get_or_create equivalent
    for notif in notifications:
        Notification.objects.get_or_create(
            recipient=notif.recipient,
            sender=notif.sender,
            notification_type='mention',
            post=notif.post,
        )


# ─────────────────────────────────────────────────────────────────────
# 3. TRENDING HASHTAGS  (Redis-cached, 5-minute TTL)
# ─────────────────────────────────────────────────────────────────────

_TRENDING_CACHE_KEY = 'trending_hashtags_v1'
_TRENDING_TTL       = 300  # seconds


def get_trending_hashtags(limit: int = 10, days: int = 1):
    """
    Returns hashtags ordered by post volume in the last `days` day(s).
    Result is cached in Redis for 5 minutes to prevent hot-path DB hits.
    """
    cached = cache.get(_TRENDING_CACHE_KEY)
    if cached is not None:
        return cached

    threshold = timezone.now() - timedelta(days=days)
    result = list(
        Hashtag.objects.filter(posts__created_at__gte=threshold)
        .annotate(post_count=Count('posts'))
        .order_by('-post_count')[:limit]
    )
    cache.set(_TRENDING_CACHE_KEY, result, _TRENDING_TTL)
    return result


def invalidate_trending_cache():
    cache.delete(_TRENDING_CACHE_KEY)


# ─────────────────────────────────────────────────────────────────────
# 4. HOT-SCORE ALGORITHM  (pure SQL – no Python loops)
# ─────────────────────────────────────────────────────────────────────
#
#   hot_score = engagement_points / (age_hours + 2) ^ 1.5
#
#   engagement_points = (likes × 5) + (comments × 10)
#                       + (shares × 20) + (views × 1)
#
#   We use denormalised counters on Post (no aggregation needed),
#   so this is a single O(n) pass fully executed inside the DB.
# ─────────────────────────────────────────────────────────────────────

def get_personalized_shorts(queryset):
    """
    Ranks Shorts by hot-score. Operates entirely in SQL.
    Input queryset must already be filtered (league, is_short, etc.).
    """
    return queryset.annotate(
        age_hours=ExpressionWrapper(
            (ExtractDay(Now() - F('created_at')) * 24)
            + ExtractHour(Now() - F('created_at'))
            + Value(2.0),
            output_field=FloatField(),
        ),
        engagement_points=ExpressionWrapper(
            (F('like_count')    * Value(5.0))
            + (F('comment_count') * Value(10.0))
            + (F('share_count')   * Value(20.0))
            + (F('view_count')    * Value(1.0)),
            output_field=FloatField(),
        ),
    ).annotate(
        hot_score=ExpressionWrapper(
            F('engagement_points') / (F('age_hours') ** Value(1.5)),
            output_field=FloatField(),
        )
    ).order_by('-hot_score')


# ─────────────────────────────────────────────────────────────────────
# 5. HOME FEED QUERYSET  (zero N+1, single SQL query)
# ─────────────────────────────────────────────────────────────────────

def get_home_feed_queryset(user, extra_filters: dict = None):
    """
    Returns the optimised base queryset for the home feed.
    • select_related  → author, league, team, parent_post chain
    • prefetch_related → profiles, hashtags
    • Exists sub-query → liked_by_me flag (no extra round-trip per post)
    • Uses denormalised counters, not COUNT() aggregations
    """
    user_like_sq = PostLike.objects.filter(post=OuterRef('pk'), user=user)

    qs = (
        Post.objects
        .select_related(
            'author',
            'author__profile',
            'league',
            'team',
            'parent_post',
            'parent_post__author',
            'parent_post__author__profile',
            'parent_post__league',
        )
        .prefetch_related('hashtags')
        .annotate(liked_by_me=ExpressionWrapper(
            Subquery(user_like_sq.values('id')[:1], output_field=FloatField()) > Value(0),
            output_field=FloatField(),
        ))
        # Use denormalised counters directly — no COUNT() needed
        .only(
            'id', 'content', 'post_type', 'media_file', 'is_short',
            'video_status', 'duration', 'created_at', 'updated_at',
            'like_count', 'comment_count', 'share_count', 'view_count',
            'is_repost',
            'author_id', 'league_id', 'team_id', 'parent_post_id',
        )
    )

    if extra_filters:
        qs = qs.filter(**extra_filters)

    return qs.order_by('-created_at')
