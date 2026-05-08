from django.db import models
from django.conf import settings
from leagues.models import League, Team
import uuid

# User helper
User = settings.AUTH_USER_MODEL

class Post(models.Model):
    """
    Represents a user post (text, image, or video) with 
    native video upload state management.
    """
    POST_TYPES = (
        ('text', 'Text'),
        ('image', 'Image'),
        ('video', 'Video'),
    )

    # Core Fields
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='posts'
    )
    content = models.TextField(blank=True, null=True)
    post_type = models.CharField(max_length=10, choices=POST_TYPES, default='text')
    media_file = models.FileField(upload_to='post_media/', blank=True, null=True)
    league = models.ForeignKey(
        League,
        on_delete=models.CASCADE,
        related_name='posts'
    )
    team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='posts'
    )

    # Native Video Management
    is_short = models.BooleanField(default=False)
    VIDEO_STATUS_CHOICES = [
        ('none', 'No Video'),
        ('pending', 'Uploading'),
        ('processing', 'Trimming/Adding Music'),
        ('ready', 'Ready to View'),
        ('failed', 'Error Processing'),
    ]
    video_status = models.CharField(
        max_length=20, 
        choices=VIDEO_STATUS_CHOICES, 
        default='none'
    )
    duration = models.PositiveIntegerField(
        default=0, 
        help_text="Duration in seconds"
    )

    # Social Features
    mentions = models.ManyToManyField(
        User, 
        related_name='mentioned_in', 
        blank=True
    )
    hashtags = models.ManyToManyField(
        'Hashtag',
        blank=True,
        related_name='posts'
    )
    parent_post = models.ForeignKey(
        'self', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='quoted_by'
    )
    is_repost = models.BooleanField(default=False)

    # Counters for Feed Algorithm
    view_count = models.PositiveIntegerField(default=0)
    like_count = models.PositiveIntegerField(default=0)
    comment_count = models.PositiveIntegerField(default=0)
    share_count = models.PositiveIntegerField(default=0)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.author.username} - {self.post_type} - {self.league.name}"


class VideoUploadSession(models.Model):
    """
    Recommended: Track chunked uploads separately to 
    prevent corrupting Post objects if upload fails.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    post = models.OneToOneField(Post, on_delete=models.CASCADE, related_name='upload_session')
    total_chunks = models.PositiveIntegerField(default=0)
    uploaded_chunks = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, default='initiated')
    created_at = models.DateTimeField(auto_now_add=True)


class Hashtag(models.Model):
    name = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"#{self.name}"


class PostLike(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    post = models.ForeignKey('Post', on_delete=models.CASCADE, related_name='likes')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'post')


class Comment(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    post = models.ForeignKey(Post, related_name='comments', on_delete=models.CASCADE)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)


class CommentLike(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    comment = models.ForeignKey(Comment, related_name='likes', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'comment')


class PostShare(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    original_post = models.ForeignKey('Post', on_delete=models.CASCADE, related_name='shares')
    comment = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)