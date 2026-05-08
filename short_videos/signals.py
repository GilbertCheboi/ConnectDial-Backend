"""
ConnectDial — Signals
=====================
Responsibilities:
  1. Keep cached_* counters on ShortVideo in sync (likes, comments, shares, views).
  2. Parse @mention tokens in VideoComment.body and create CommentMention rows.
  3. Notify @mentioned users (stub — wire to your notification backend).
  4. Bust the per-user feed cache when a new video is published.
"""

import re
from django.db import models
from django.db.models.signals import post_save, post_delete, m2m_changed
from django.dispatch import receiver
from django.conf import settings

from .models import (
    VideoLike, VideoComment, CommentMention,
    VideoShare, VideoView, ShortVideo,
)

# Lazy import to avoid circular imports
def _get_user_model():
    from django.contrib.auth import get_user_model
    return get_user_model()


# ─────────────────────────────────────────────────────────────────────────────
# HELPER
# ─────────────────────────────────────────────────────────────────────────────

def _update_cached(video_id, field, delta):
    """Atomic F()-based counter update — safe under concurrent writes."""
    ShortVideo.objects.filter(pk=video_id).update(**{field: models.F(field) + delta})


# ─────────────────────────────────────────────────────────────────────────────
# LIKES
# ─────────────────────────────────────────────────────────────────────────────

@receiver(post_save, sender=VideoLike)
def like_created(sender, instance, created, **kwargs):
    if created:
        _update_cached(instance.video_id, 'cached_likes', 1)


@receiver(post_delete, sender=VideoLike)
def like_deleted(sender, instance, **kwargs):
    _update_cached(instance.video_id, 'cached_likes', -1)


# ─────────────────────────────────────────────────────────────────────────────
# COMMENTS  (counter + @mention resolution)
# ─────────────────────────────────────────────────────────────────────────────

_MENTION_RE = re.compile(r'@([\w.]+)')   # matches @username or @user.name


def _resolve_mentions(body: str) -> list:
    """
    Extract @username handles from comment body and return matching User objects.
    Returns an empty list if no handles found or none match existing accounts.
    """
    User = _get_user_model()
    handles = set(_MENTION_RE.findall(body))
    if not handles:
        return []
    return list(User.objects.filter(username__in=handles))


def _create_mention_rows(comment: VideoComment, users: list):
    """
    Bulk-create CommentMention rows, skipping duplicates.
    Uses ignore_conflicts so re-saves don't raise IntegrityError.
    """
    CommentMention.objects.bulk_create(
        [CommentMention(comment=comment, user=u) for u in users],
        ignore_conflicts=True,
    )


def _notify_mentioned_users(comment: VideoComment, users: list):
    """
    Stub: send in-app / push notifications to @mentioned users.
    Wire this to your notification backend (e.g. django-notifications,
    FCM, APNs).
    """
    for user in users:
        # TODO: replace with real notification dispatch
        pass


@receiver(post_save, sender=VideoComment)
def comment_saved(sender, instance, created, **kwargs):
    # 1. Update cached counter only on creation
    if created:
        _update_cached(instance.video_id, 'cached_comments', 1)

    # 2. Resolve @mentions every save (handles edits too)
    mentioned = _resolve_mentions(instance.body)
    if mentioned:
        # Remove stale mentions on edit before re-creating
        if not created:
            CommentMention.objects.filter(comment=instance).delete()
        _create_mention_rows(instance, mentioned)

        if created:
            _notify_mentioned_users(instance, mentioned)


@receiver(post_delete, sender=VideoComment)
def comment_deleted(sender, instance, **kwargs):
    _update_cached(instance.video_id, 'cached_comments', -1)
    # CommentMention rows cascade-delete automatically via FK.


# ─────────────────────────────────────────────────────────────────────────────
# SHARES
# ─────────────────────────────────────────────────────────────────────────────

@receiver(post_save, sender=VideoShare)
def share_created(sender, instance, created, **kwargs):
    if created:
        _update_cached(instance.video_id, 'cached_shares', 1)


# ─────────────────────────────────────────────────────────────────────────────
# VIEWS
# ─────────────────────────────────────────────────────────────────────────────

@receiver(post_save, sender=VideoView)
def view_created(sender, instance, created, **kwargs):
    if created:
        _update_cached(instance.video_id, 'cached_views', 1)


# ─────────────────────────────────────────────────────────────────────────────
# NEW VIDEO → bust feed caches for followers
# ─────────────────────────────────────────────────────────────────────────────

@receiver(post_save, sender=ShortVideo)
def video_published(sender, instance, created, **kwargs):
    """
    When a new video is posted, bust the feed cache for:
      - the author themselves
      - all users who follow the author (if your follow model exposes .followers)

    Adjust the follower query to match your actual Follow / UserProfile model.
    """
    if not created:
        return

    from .feed_algorithm import bust_feed_cache

    # Always bust the author's own feed
    bust_feed_cache(instance.author_id)

    # Bust followers' feeds — adapt to your follow model
    try:
        follower_ids = (
            instance.author.followers          # e.g. a related_name on a Follow model
            .values_list('follower_id', flat=True)
        )
        for uid in follower_ids:
            bust_feed_cache(uid)
    except AttributeError:
        # Follow relationship not set up yet — skip silently
        pass