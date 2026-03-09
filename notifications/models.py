from django.db import models
from django.conf import settings


class DeviceToken(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name='device_tokens', on_delete=models.CASCADE
    )
    token = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.token}"


User = settings.AUTH_USER_MODEL


class Notification(models.Model):
    NOTIFICATION_TYPES = (
        ('like', 'Like'),
        ('comment', 'Comment'),
        ('follow', 'Follow'),
        ('share', 'Share'),
    )

    recipient = models.ForeignKey(
        User,
        related_name='notifications',
        on_delete=models.CASCADE
    )
    actor = models.ForeignKey(
        User,
        related_name='actions',
        on_delete=models.CASCADE
    )
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES)

    post = models.ForeignKey(
        'posts.Post',
        null=True,
        blank=True,
        on_delete=models.CASCADE
    )

    comment = models.ForeignKey(
        'posts.Comment',
        null=True,
        blank=True,
        on_delete=models.CASCADE
    )

    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

