from django.db import models
from django.conf import settings
from django.core.cache import cache
from leagues.models import League, Team
import uuid

User = settings.AUTH_USER_MODEL


class Hashtag(models.Model):
    name = models.CharField(max_length=100, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['name']),
        ]

    def __str__(self):
        return f"#{self.name}"


class Post(models.Model):
    """
    Represents a user post (text, image, or video) with
    native video upload state management and hot-score caching.
    """
    POST_TYPES = (
        ('text',  'Text'),
        ('image', 'Image'),
        ('video', 'Video'),
    )
    VIDEO_STATUS_CHOICES = [
        ('none',       'No Video'),
        ('pending',    'Uploading'),
        ('processing', 'Trimming/Adding Music'),
        ('ready',      'Ready to View'),
        ('failed',     'Error Processing'),
    ]

    # ── Core ──────────────────────────────────────────────────────────
    author = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='posts', db_index=True
    )
    content    = models.TextField(blank=True, null=True)
    post_type  = models.CharField(max_length=10, choices=POST_TYPES, default='text')

    # Kept for backward compatibility (single file, e.g. shorts video)
    media_file = models.FileField(upload_to='post_media/', blank=True, null=True)

    league = models.ForeignKey(
        League, on_delete=models.CASCADE, related_name='posts', db_index=True
    )
    team = models.ForeignKey(
        Team, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='posts', db_index=True
    )

    # ── Native Video ──────────────────────────────────────────────────
    is_short     = models.BooleanField(default=False, db_index=True)
    video_status = models.CharField(
        max_length=20, choices=VIDEO_STATUS_CHOICES, default='none', db_index=True
    )
    duration = models.PositiveIntegerField(default=0, help_text="Duration in seconds")

    # ── Social Features ───────────────────────────────────────────────
    mentions = models.ManyToManyField(
        User, related_name='mentioned_in', blank=True
    )
    hashtags = models.ManyToManyField(
        'Hashtag', blank=True, related_name='posts'
    )
    parent_post = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='quoted_by', db_index=True
    )
    is_repost = models.BooleanField(default=False)

    # ── Denormalised counters (updated atomically via F()) ────────────
    view_count    = models.PositiveIntegerField(default=0)
    like_count    = models.PositiveIntegerField(default=0)
    comment_count = models.PositiveIntegerField(default=0)
    share_count   = models.PositiveIntegerField(default=0)

    # ── Timestamps ────────────────────────────────────────────────────
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['league', '-created_at']),
            models.Index(fields=['author', '-created_at']),
            models.Index(fields=['is_short', 'video_status', '-created_at']),
        ]

    def __str__(self):
        return f"{self.author_id} – {self.post_type} – {self.league_id}"

    def get_media_url(self, request=None):
        if not self.media_file:
            return None
        url = self.media_file.url
        if request:
            return request.build_absolute_uri(url)
        return url

    # ── Atomic counter helpers ────────────────────────────────────────
    def increment_view(self):
        Post.objects.filter(pk=self.pk).update(view_count=models.F('view_count') + 1)

    def increment_like(self):
        Post.objects.filter(pk=self.pk).update(like_count=models.F('like_count') + 1)

    def decrement_like(self):
        Post.objects.filter(pk=self.pk).update(
            like_count=models.Case(
                models.When(like_count__gt=0, then=models.F('like_count') - 1),
                default=models.Value(0),
                output_field=models.PositiveIntegerField(),
            )
        )

    def increment_comment(self):
        Post.objects.filter(pk=self.pk).update(comment_count=models.F('comment_count') + 1)

    def decrement_comment(self):
        Post.objects.filter(pk=self.pk).update(
            comment_count=models.Case(
                models.When(comment_count__gt=0, then=models.F('comment_count') - 1),
                default=models.Value(0),
                output_field=models.PositiveIntegerField(),
            )
        )

    def increment_share(self):
        Post.objects.filter(pk=self.pk).update(share_count=models.F('share_count') + 1)


# ── NEW: Multi-media support ───────────────────────────────────────────────
class PostMedia(models.Model):
    """
    Stores multiple images/videos for a single Post.
    A Post can have up to 5 PostMedia entries (enforced in the view).
    post.media_file is kept for backward compat (shorts single video).
    """
    MEDIA_TYPES = (
        ('image', 'Image'),
        ('video', 'Video'),
    )

    post       = models.ForeignKey(
        Post, on_delete=models.CASCADE, related_name='media_files'
    )
    file       = models.FileField(upload_to='post_media/')
    media_type = models.CharField(max_length=10, choices=MEDIA_TYPES, default='image')
    order      = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order']
        indexes  = [
            models.Index(fields=['post', 'order']),
        ]

    def __str__(self):
        return f"PostMedia(post={self.post_id}, type={self.media_type}, order={self.order})"


class VideoUploadSession(models.Model):
    """
    Tracks chunked uploads separately to avoid corrupting Post objects.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user      = models.ForeignKey(User, on_delete=models.CASCADE)
    post      = models.OneToOneField(Post, on_delete=models.CASCADE, related_name='upload_session')
    total_chunks    = models.PositiveIntegerField(default=0)
    uploaded_chunks = models.PositiveIntegerField(default=0)
    status    = models.CharField(max_length=20, default='initiated')
    created_at = models.DateTimeField(auto_now_add=True)


class PostLike(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='likes')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'post')
        indexes = [
            models.Index(fields=['post', 'user']),
        ]


class Comment(models.Model):
    user    = models.ForeignKey(User, on_delete=models.CASCADE, db_index=True)
    post    = models.ForeignKey(Post, related_name='comments', on_delete=models.CASCADE, db_index=True)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['post', '-created_at']),
        ]


class CommentLike(models.Model):
    user    = models.ForeignKey(User, on_delete=models.CASCADE)
    comment = models.ForeignKey(Comment, related_name='likes', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'comment')


class PostShare(models.Model):
    user          = models.ForeignKey(User, on_delete=models.CASCADE)
    original_post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='shares')
    comment       = models.TextField(blank=True, null=True)
    created_at    = models.DateTimeField(auto_now_add=True)