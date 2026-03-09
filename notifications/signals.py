from django.db.models.signals import post_save
from django.dispatch import receiver

from posts.models import PostLike, Comment, PostShare
from feeds.models import UserFollow
from notifications.models import Notification



@receiver(post_save, sender=PostLike)
def like_notification(sender, instance, created, **kwargs):
    if not created:
        return

    post = instance.post
    if instance.user == post.author:
        return

    Notification.objects.create(
        recipient=post.author,
        actor=instance.user,
        notification_type='like',
        post=post
    )


@receiver(post_save, sender=Comment)
def comment_notification(sender, instance, created, **kwargs):
    if not created:
        return

    post = instance.post
    if instance.user == post.author:
        return

    Notification.objects.create(
        recipient=post.author,
        actor=instance.user,
        notification_type='comment',
        post=post,
        comment=instance
    )


@receiver(post_save, sender=UserFollow)
def follow_notification(sender, instance, created, **kwargs):
    if not created:
        return

    if instance.follower == instance.following:
        return

    Notification.objects.create(
        recipient=instance.following,
        actor=instance.follower,
        notification_type='follow'
    )


@receiver(post_save, sender=PostShare)
def share_notification(sender, instance, created, **kwargs):
    if not created:
        return

    post = instance.original_post
    if instance.user == post.author:
        return

    Notification.objects.create(
        recipient=post.author,
        actor=instance.user,
        notification_type='share',
        post=post
    )


