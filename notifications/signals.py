from django.db.models.signals import post_save
from django.dispatch import receiver
from posts.models import PostLike, Comment, Post
from users.models import Follow
from .models import Notification
from .tasks import send_push_notification_task # 🚀 Import your Celery task



# 1. Like SIGNAL

@receiver(post_save, sender=PostLike)
def create_like_notification(sender, instance, created, **kwargs):
    if created:
        # Avoid notifying yourself if you like your own post
        if instance.user != instance.post.author:
            Notification.objects.create(
                recipient=instance.post.author,
                sender=instance.user,
                notification_type='like',
                post=instance.post
            )
# 2. Follow SIGNAL

@receiver(post_save, sender=Follow)
def create_follow_notification(sender, instance, created, **kwargs):
    if created:
        Notification.objects.create(
            recipient=instance.followed,
            sender=instance.follower,
            notification_type='follow'
        )

# 3. COMMENT SIGNAL
@receiver(post_save, sender=Comment)
def create_comment_notification(sender, instance, created, **kwargs):
    if created and instance.user != instance.post.author:
        Notification.objects.create(
            recipient=instance.post.author,
            sender=instance.user,
            notification_type='comment',
            post=instance.post
        )

# 4. REPOST SIGNAL 
# (Assuming a repost is a Post where parent_post is not null)
@receiver(post_save, sender=Post)
def create_repost_notification(sender, instance, created, **kwargs):
    if created and instance.parent_post and instance.author != instance.parent_post.author:
        Notification.objects.create(
            recipient=instance.parent_post.author,
            sender=instance.author,
            notification_type='repost',
            post=instance.parent_post
        )

@receiver(post_save, sender=Notification)
def trigger_push_notification(sender, instance, created, **kwargs):
    if created:
        message_map = {
            'like': f"{instance.sender.username} liked your post",
            'follow': f"{instance.sender.username} started following you",
            'comment': f"{instance.sender.username} commented on your post",
            'repost': f"{instance.sender.username} reposted your content",
        }
        
        display_message = message_map.get(instance.notification_type, "New activity")

        # Determine which ID to send for navigation
        # For likes/comments, send the Post ID. For follows, send the Sender ID.
        nav_id = instance.post.id if instance.post else instance.sender.id

        send_push_notification_task.delay(
            user_id=instance.recipient.id,
            title="ConnectDial",
            message=display_message,
            notification_type=instance.notification_type,
            object_id=nav_id
        )