from django.db import models
from django.conf import settings 

class Notification(models.Model):
    NOTIFICATION_TYPES = (
        ('like', 'Like'),
        ('comment', 'Comment'),
        ('repost', 'Repost'),
        ('follow', 'Follow'),
    )

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='notifications'
        # 🚀 'on_index' was removed from here
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='sent_notifications'
    )
    
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES)
    
    # Keeping this as a string 'posts.Post' prevents circular imports
    post = models.ForeignKey(
        'posts.Post', 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True
    )
    
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.sender} -> {self.recipient} ({self.notification_type})"