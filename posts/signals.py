from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Post
from .services import process_post_metadata, handle_mentions
from django.db.models import F, ExpressionWrapper, FloatField, Count
from django.utils import timezone
from datetime import timedelta

@receiver(post_save, sender=Post)
def handle_post_extras(sender, instance, created, **kwargs):
    """
    Only one signal is needed to handle all metadata.
    """
    # We use process_post_metadata for both new posts and edits
    # to ensure mentions/hashtags stay in sync with the content.
    process_post_metadata(instance)



@receiver(post_save, sender=Post)
def create_post_related_notifications(sender, instance, created, **kwargs):
    if created:
        # 1. Handle Reposts (your existing logic)
        if instance.parent_post and instance.author != instance.parent_post.author:
            Notification.objects.create(
                recipient=instance.parent_post.author,
                sender=instance.author,
                notification_type='repost',
                post=instance.parent_post
            )
        
        # 2. Handle Mentions 🚀
        handle_mentions(instance)

# Update your trigger_push_notification message_map
@receiver(post_save, sender=Notification)
def trigger_push_notification(sender, instance, created, **kwargs):
    if created:
        message_map = {
            'like': f"{instance.sender.username} liked your post",
            'follow': f"{instance.sender.username} started following you",
            'comment': f"{instance.sender.username} commented on your post",
            'repost': f"{instance.sender.username} reposted your content",
            'mention': f"{instance.sender.username} mentioned you in a post", # 🚀 Added
        }
        # ... rest of your task.delay logic ...


