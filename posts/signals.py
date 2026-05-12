"""
signals.py – ConnectDial Post signals
──────────────────────────────────────
Single post_save receiver handles ALL post-save side-effects
so Django doesn't fire multiple DB transactions per save.
"""

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import Post, Comment


# ─────────────────────────────────────────────────────────────────────
# POST SIGNALS
# ─────────────────────────────────────────────────────────────────────

@receiver(post_save, sender=Post)
def on_post_saved(sender, instance, created, **kwargs):
    """
    Consolidated handler: metadata + notifications in one signal.
    Runs in a deferred (post-commit) fashion when Celery is available.
    """
    from .services import process_post_metadata, handle_mentions

    # 1. Always sync hashtags + mentions (handles edits too)
    process_post_metadata(instance)

    if created:
        # 2. Mention notifications (only for new posts)
        handle_mentions(instance)

        # 3. Repost notification
        if instance.parent_post_id and instance.author_id != instance.parent_post.author_id:
            _notify_repost(instance)

        # 4. Invalidate trending hashtag cache
        from .services import invalidate_trending_cache
        invalidate_trending_cache()


def _notify_repost(instance):
    try:
        from notifications.models import Notification
        Notification.objects.get_or_create(
            recipient        = instance.parent_post.author,
            sender           = instance.author,
            notification_type='repost',
            post             = instance.parent_post,
        )
    except Exception:
        pass  # Notifications are non-critical; never break the save


# ─────────────────────────────────────────────────────────────────────
# NOTIFICATION → PUSH  (Celery task, non-blocking)
# ─────────────────────────────────────────────────────────────────────

def _get_notification_model():
    try:
        from notifications.models import Notification
        return Notification
    except ImportError:
        return None


Notification = _get_notification_model()

if Notification:
    @receiver(post_save, sender=Notification)
    def trigger_push_notification(sender, instance, created, **kwargs):
        if not created:
            return

        message_map = {
            'like':    f"{instance.sender.username} liked your post",
            'follow':  f"{instance.sender.username} started following you",
            'comment': f"{instance.sender.username} commented on your post",
            'repost':  f"{instance.sender.username} reposted your content",
            'mention': f"{instance.sender.username} mentioned you in a post",
        }
        message = message_map.get(instance.notification_type)
        if not message:
            return

        # Kick off Celery push task (non-blocking)
        try:
            from notifications.tasks import send_push_notification
            send_push_notification.delay(
                user_id = instance.recipient_id,
                title   = "ConnectDial",
                body    = message,
            )
        except Exception:
            pass  # Push is best-effort
