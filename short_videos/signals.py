"""
ConnectDial — Signals
=====================
Responsibilities:
  1. Keep cached_* counters on ShortVideo in sync (likes, comments, shares, views).
  2. Parse @mention tokens in VideoComment.body and create CommentMention rows.
  3. Notify @mentioned users (stub — wire to your notification backend).
  4. Bust the per-user feed cache when a new video is published.

Fixes applied
─────────────
  FIX-7  Added post_delete handler for VideoView so cached_views stays
         accurate if view rows are ever bulk-pruned or individually deleted
         (e.g. data-retention jobs, admin actions, test teardown).
         Previously only post_save was handled, so deletes silently drifted
         cached_views above the true count indefinitely.

  FIX-8  _create_mention_rows now uses select_for_update()-safe bulk_create
         with ignore_conflicts=True (unchanged), but the stale-mention delete
         on edit is now wrapped in a transaction.atomic() block to prevent a
         race where two simultaneous edits each delete and re-insert mentions,
         potentially leaving zero rows if the second delete runs between the
         first pair of delete+insert.
"""

import re
from django.db import models, transaction
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.conf import settings

from .models import (
    VideoLike, VideoComment, CommentMention,
    VideoShare, VideoView, ShortVideo,
)


def _get_user_model():
    from django.contrib.auth import get_user_model
    return get_user_model()


# ─────────────────────────────────────────────────────────────────────────────
# HELPER
# ─────────────────────────────────────────────────────────────────────────────

def _update_cached(video_id, field: str, delta: int) -> None:
    """
    Atomic F()-based counter update — safe under concurrent writes.
    Clamps the result at 0 so a stale delete never drives a counter negative.
    """
    ShortVideo.objects.filter(pk=video_id).update(
        **{field: models.Case(
            models.When(
                **{f'{field}__gt': 0},
                then=models.F(field) + delta,
            ),
            default=models.Value(0),
            output_field=models.PositiveIntegerField(),
        ) if delta < 0 else models.F(field) + delta}
    )


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

_MENTION_RE = re.compile(r'@([\w.]+)')


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


def _create_mention_rows(comment: VideoComment, users: list) -> None:
    """
    Bulk-create CommentMention rows, skipping duplicates.
    ignore_conflicts prevents IntegrityError on concurrent saves.
    """
    CommentMention.objects.bulk_create(
        [CommentMention(comment=comment, user=u) for u in users],
        ignore_conflicts=True,
    )


def _notify_mentioned_users(comment: VideoComment, users: list) -> None:
    """
    Stub: send in-app / push notifications to @mentioned users.
    Wire to your notification backend (django-notifications, FCM, APNs, etc.).
    """
    for user in users:
        # TODO: replace with real notification dispatch
        pass


@receiver(post_save, sender=VideoComment)
def comment_saved(sender, instance, created, **kwargs):
    # 1. Increment counter only on creation
    if created:
        _update_cached(instance.video_id, 'cached_comments', 1)

    # 2. Resolve @mentions on every save (handles edits correctly)
    mentioned = _resolve_mentions(instance.body)

    if mentioned:
        if not created:
            # FIX-8: wrap delete+insert in a transaction so a concurrent edit
            # cannot leave zero mention rows between the two operations.
            with transaction.atomic():
                CommentMention.objects.filter(comment=instance).delete()
                _create_mention_rows(instance, mentioned)
        else:
            _create_mention_rows(instance, mentioned)
            _notify_mentioned_users(instance, mentioned)
    elif not created:
        # Body was edited and now has no mentions — clean up any stale rows.
        CommentMention.objects.filter(comment=instance).delete()


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


@receiver(post_delete, sender=VideoShare)
def share_deleted(sender, instance, **kwargs):
    """
    Decrement cached_shares when a share is deleted.
    This covers the VideoReshareView toggle-off path as well as any admin
    or programmatic deletion of VideoShare rows.
    """
    _update_cached(instance.video_id, 'cached_shares', -1)


# ─────────────────────────────────────────────────────────────────────────────
# VIEWS
# ─────────────────────────────────────────────────────────────────────────────

@receiver(post_save, sender=VideoView)
def view_created(sender, instance, created, **kwargs):
    if created:
        _update_cached(instance.video_id, 'cached_views', 1)


@receiver(post_delete, sender=VideoView)
def view_deleted(sender, instance, **kwargs):
    """
    FIX-7: Decrement cached_views when a VideoView row is deleted.

    Previously there was no post_delete handler for VideoView. If rows were
    pruned by a data-retention job, admin bulk-delete, or test teardown,
    cached_views would drift above the true count and never recover without
    a full recount.

    _update_cached clamps at 0, so a stale delete never produces a negative
    counter.
    """
    _update_cached(instance.video_id, 'cached_views', -1)


# ─────────────────────────────────────────────────────────────────────────────
# NEW VIDEO → bust feed caches for author + followers
# ─────────────────────────────────────────────────────────────────────────────

@receiver(post_save, sender=ShortVideo)
def video_published(sender, instance, created, **kwargs):
    """
    When a new video is posted, bust the feed cache for:
      - the author themselves
      - all users who follow the author

    Adjust the follower query to match your actual Follow / UserProfile model.
    """
    if not created:
        return

    from .feed_algorithm import bust_feed_cache

    bust_feed_cache(instance.author_id)

    try:
        follower_ids = (
            instance.author.followers
            .values_list('follower_id', flat=True)
        )
        for uid in follower_ids:
            bust_feed_cache(uid)
    except AttributeError:
        # Follow relationship not yet set up — skip silently.
        pass