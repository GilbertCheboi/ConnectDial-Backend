from django.db import models
from django.conf import settings
from leagues.models import League, Team

from django.core.files.storage import default_storage

class Post(models.Model):
    """
    Represents a user post (text, image, or video)
    """
    POST_TYPES = (
        ('text', 'Text'),
        ('image', 'Image'),
        ('video', 'Video'),
    )

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_short = models.BooleanField(default=False)
    mentions = models.ManyToManyField(
        
        settings.AUTH_USER_MODEL, 
        related_name='mentioned_in', 
        blank=True
    )

    hashtags = models.ManyToManyField(
        'Hashtag', # We'll define this model next
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

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.author.username} - {self.post_type} - {self.league.name}"

    view_count = models.PositiveIntegerField(default=0)
    like_count = models.PositiveIntegerField(default=0)
    comment_count = models.PositiveIntegerField(default=0)
    share_count = models.PositiveIntegerField(default=0)




User = settings.AUTH_USER_MODEL

class VideoEngagement(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='engagements')
    
    watch_time = models.FloatField(default=0) 
    is_completed = models.BooleanField(default=False)
    rewatched = models.BooleanField(default=False)
    
    # ADD THIS: Allows us to see "User X spent 5 minutes watching Premier League today"
    # without doing complex database joins.
    league_id = models.IntegerField(null=True, blank=True) 
    
    timestamp = models.DateTimeField(auto_now_add=True)


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
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )
    post = models.ForeignKey(
        Post,
        related_name='comments',
        on_delete=models.CASCADE
    )
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)



class CommentLike(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )
    comment = models.ForeignKey(
        Comment,
        related_name='likes',
        on_delete=models.CASCADE
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'comment')



class PostShare(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    original_post = models.ForeignKey(
        'Post',
        on_delete=models.CASCADE,
        related_name='shares'
    )
    comment = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

