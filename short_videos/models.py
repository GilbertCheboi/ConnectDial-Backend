"""
ConnectDial — Short Video Models
=================================
Covers:
  - ShortVideo        : the core video entity (0s – 7200s / 2hrs)
  - VideoLike         : user like on a video
  - VideoComment      : threaded comment with @mention tagging
  - CommentMention    : M2M through-table for @tagged users in comments
  - VideoShare        : share action
  - VideoView         : view event with watch_time for completion tracking
"""

import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.db.models import Count
from leagues.models import League, Team

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def short_video_upload_path(instance, filename):
    ext = filename.rsplit('.', 1)[-1]
    return f"shorts/{instance.pk}/{uuid.uuid4().hex}.{ext}"


# ─────────────────────────────────────────────────────────────────────────────
# SHORT VIDEO
# ─────────────────────────────────────────────────────────────────────────────

class ShortVideo(models.Model):
    """
    A short-form video post.

    Duration range: 0 – 7 200 seconds (0s – 2 hrs).
    Cached counters are maintained via signals so the feed algorithm never
    issues aggregate COUNT() queries at read time.
    """

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    author      = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='short_videos',
    )

    video       = models.FileField(upload_to=short_video_upload_path)
    thumbnail   = models.ImageField(upload_to='shorts/thumbnails/', blank=True, null=True)
    caption     = models.TextField(blank=True, max_length=2200)

    # Contextual tags — both optional
    league      = models.ForeignKey(
        'leagues.League', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='short_videos',
    )
    team = models.ForeignKey(
            'leagues.Team', null=True, blank=True,
            on_delete=models.SET_NULL, related_name='short_videos'
        )

    # Duration in seconds — 0 to 7200 (2 hrs)
    duration    = models.PositiveIntegerField(
        default=0,
        help_text="Video duration in seconds (0 – 7200).",
    )

    # ── Denormalised counters (updated by signals, never by views) ──────────
    cached_likes    = models.PositiveIntegerField(default=0, db_index=True)
    cached_comments = models.PositiveIntegerField(default=0)
    cached_shares   = models.PositiveIntegerField(default=0)
    cached_views    = models.PositiveIntegerField(default=0)

    created_at  = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes  = [
            models.Index(fields=['league', '-created_at']),
            models.Index(fields=['team', '-created_at']),
            models.Index(fields=['author', '-created_at']),
        ]

    def __str__(self):
        return f"ShortVideo({self.id}) by {self.author_id}"

    @property
    def share_url(self):
        return f"https://connectdial.com/shorts/{self.pk}/"

    @property
    def og_title(self):
        return f"{self.author.username}: {self.caption[:80]}" if self.caption else str(self.id)

    @property
    def og_description(self):
        return self.caption[:200] if self.caption else ""

    @property
    def duration_display(self):
        """Return human-readable duration: '1:23' or '1:02:45'."""
        s = self.duration
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        if h:
            return f"{h}:{m:02d}:{sec:02d}"
        return f"{m}:{sec:02d}"


# ─────────────────────────────────────────────────────────────────────────────
# ENGAGEMENT
# ─────────────────────────────────────────────────────────────────────────────

class VideoLike(models.Model):
    user    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='video_likes')
    video   = models.ForeignKey(ShortVideo, on_delete=models.CASCADE, related_name='likes')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'video')


class VideoComment(models.Model):
    """
    Comment on a ShortVideo with optional threading and @mention support.

    - `parent` allows one level of threaded replies.
    - `mentioned_users` is populated by parsing @username tokens in `body`
      (see signals.py) and stored in the CommentMention through-table.

    NOTE: The DB column for `author` is `user_id` (legacy name from initial
    migration). We keep the Python attribute as `author` for readability and
    use db_column='user_id' to bridge the mismatch without a schema migration.
    """
    id      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    video   = models.ForeignKey(ShortVideo, on_delete=models.CASCADE, related_name='comments')
    author  = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='video_comments',
        db_column='user_id',   # ← actual column in short_videos_videocomment
    )
    parent  = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.CASCADE, related_name='replies',
    )
    body    = models.TextField(max_length=1000, db_column='text')

    # @mentioned users resolved at save time
    mentioned_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through='CommentMention',
        related_name='comment_mentions',
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        indexes  = [
            models.Index(fields=['video', 'created_at']),
            models.Index(fields=['parent']),
        ]

    def __str__(self):
        return f"Comment({self.id}) on {self.video_id} by {self.author_id}"


class CommentMention(models.Model):
    """Through-model recording which users were @tagged in a comment."""
    comment     = models.ForeignKey(VideoComment, on_delete=models.CASCADE, related_name='mentions')
    user        = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='mentioned_in_comments',
    )
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('comment', 'user')

    def __str__(self):
        return f"@{self.user_id} in comment {self.comment_id}"


class VideoShare(models.Model):
    PLATFORM_CHOICES = [
        ('whatsapp',  'WhatsApp'),
        ('telegram',  'Telegram'),
        ('twitter',   'Twitter / X'),
        ('facebook',  'Facebook'),
        ('instagram', 'Instagram'),
        ('copy_link', 'Copy Link'),
        ('other',     'Other'),
    ]

    user        = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='video_shares')
    video       = models.ForeignKey(ShortVideo, on_delete=models.CASCADE, related_name='shares')
    platform    = models.CharField(max_length=20, choices=PLATFORM_CHOICES, default='other')
    created_at  = models.DateTimeField(auto_now_add=True)


class VideoView(models.Model):
    """
    Records a single view event.

    Fields
    ──────
    watch_time : seconds the user actually watched — used to compute
                 watch_ratio in the feed algorithm.
    completed  : True if the user watched to (or near) the end of the video.
                 Computed automatically on save: watch_time >= 90% of duration.
                 Stored explicitly so signals/analytics can filter on it cheaply
                 without recomputing the ratio each time.
    """
    user        = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='video_views',
    )
    video       = models.ForeignKey(ShortVideo, on_delete=models.CASCADE, related_name='views')
    watch_time  = models.FloatField(default=0.0, help_text="Seconds watched.")

    completed   = models.BooleanField(
        default=False,
        help_text="True if watch_time >= 90% of video duration.",
    )

    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['video', 'created_at']),
            models.Index(fields=['user', 'created_at']),
        ]

    def save(self, *args, **kwargs):
        """
        Auto-compute `completed` before saving.
        A view counts as completed if the user watched at least 90% of
        the video. Falls back to False if duration is 0 (unknown length).
        """
        duration = self.video.duration if self.video_id else 0
        if duration > 0:
            self.completed = self.watch_time >= (duration * 0.9)
        else:
            self.completed = False
        super().save(*args, **kwargs)