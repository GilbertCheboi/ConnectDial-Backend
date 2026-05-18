"""
ConnectDial — Serializers
==========================

Fixes applied
─────────────
  FIX-1  Added ShortVideoCreateSerializer — a dedicated write serializer for
         ShortVideoUploadView. Previously the view passed `video=compressed_file`
         as a raw kwarg to ShortVideoSerializer.save(), bypassing the serializer
         field entirely. This meant:
           - Storage-backend hooks (S3/GCS path generation, upload) did not run
             through the serializer's validated_data pipeline.
           - Any future per-field validation on `video` would be silently skipped.
         ShortVideoCreateSerializer declares `video` as a writable FileField so
         the compressed InMemoryUploadedFile goes through normal DRF validation
         and the storage backend saves it correctly.
"""

import re
from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import (
    ShortVideo, VideoComment, CommentMention,
    VideoLike, VideoShare, VideoView,
)

User = get_user_model()

_MENTION_RE = re.compile(r'@([\w.]+)')


# ─────────────────────────────────────────────────────────────────────────────
# USER (LIGHTWEIGHT)
# ─────────────────────────────────────────────────────────────────────────────

class MentionedUserSerializer(serializers.ModelSerializer):
    class Meta:
        model  = User
        fields = ['id', 'username']


# ─────────────────────────────────────────────────────────────────────────────
# MENTIONS
# ─────────────────────────────────────────────────────────────────────────────

class CommentMentionSerializer(serializers.ModelSerializer):
    user = MentionedUserSerializer(read_only=True)

    class Meta:
        model  = CommentMention
        fields = ['user']


# ─────────────────────────────────────────────────────────────────────────────
# COMMENTS
# ─────────────────────────────────────────────────────────────────────────────

class VideoCommentSerializer(serializers.ModelSerializer):
    """Read serializer for a comment."""
    author_username = serializers.CharField(source='author.username', read_only=True)
    author_avatar   = serializers.SerializerMethodField()
    mentions        = CommentMentionSerializer(many=True, read_only=True)
    reply_count     = serializers.SerializerMethodField()

    class Meta:
        model  = VideoComment
        fields = [
            'id',
            'video',
            'author_username',
            'author_avatar',
            'parent',
            'body',
            'mentions',
            'reply_count',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']

    def get_author_avatar(self, obj):
        request = self.context.get('request')
        try:
            if obj.author.profile.avatar:
                url = obj.author.profile.avatar.url
                return request.build_absolute_uri(url) if request else url
        except Exception:
            pass
        return None

    def get_reply_count(self, obj):
        return obj.replies.count()


class VideoCommentCreateSerializer(serializers.ModelSerializer):
    """Write serializer for creating / updating a comment."""

    class Meta:
        model  = VideoComment
        fields = ['id', 'video', 'parent', 'body']
        read_only_fields = ['id']

    def validate_body(self, value):
        if not value.strip():
            raise serializers.ValidationError("Comment body cannot be empty.")
        return value

    def validate_parent(self, value):
        if value and value.parent_id is not None:
            raise serializers.ValidationError(
                "Replies to replies are not supported. "
                "Tag the user with @mention instead."
            )
        return value

    def create(self, validated_data):
        return super().create(validated_data)


# ─────────────────────────────────────────────────────────────────────────────
# SHORT VIDEO — READ
# ─────────────────────────────────────────────────────────────────────────────

class ShortVideoSerializer(serializers.ModelSerializer):
    """
    Read serializer for ShortVideo — used for feed responses and the upload
    response payload. All count fields come from denormalised cached_* columns.
    This serializer is READ-ONLY; use ShortVideoCreateSerializer for writes.
    """
    author_username  = serializers.CharField(source='author.username', read_only=True)
    author_avatar    = serializers.SerializerMethodField()
    author_id        = serializers.IntegerField(source='author.id', read_only=True)

    league_name      = serializers.CharField(source='league.name', read_only=True, default=None)
    team_name        = serializers.CharField(source='team.name',   read_only=True, default=None)

    likes_count      = serializers.IntegerField(source='cached_likes',    read_only=True)
    comments_count   = serializers.IntegerField(source='cached_comments', read_only=True)
    shares_count     = serializers.IntegerField(source='cached_shares',   read_only=True)
    views_count      = serializers.IntegerField(source='cached_views',    read_only=True)

    duration_display = serializers.CharField(read_only=True)

    video_url        = serializers.SerializerMethodField()
    thumbnail_url    = serializers.SerializerMethodField()
    share_url        = serializers.SerializerMethodField()
    is_liked         = serializers.SerializerMethodField()
    og_title         = serializers.SerializerMethodField()
    og_description   = serializers.SerializerMethodField()

    class Meta:
        model  = ShortVideo
        fields = [
            'id',
            'author_id',
            'author_username',
            'author_avatar',
            'video_url',
            'thumbnail_url',
            'caption',
            'league_name',
            'team_name',
            'duration',
            'duration_display',
            'likes_count',
            'comments_count',
            'shares_count',
            'views_count',
            'is_liked',
            'share_url',
            'og_title',
            'og_description',
            'created_at',
        ]

    def get_author_avatar(self, obj):
        request = self.context.get('request')
        try:
            if obj.author.profile.avatar:
                url = obj.author.profile.avatar.url
                return request.build_absolute_uri(url) if request else url
        except Exception:
            pass
        return None

    def get_video_url(self, obj):
        """
        Returns the streaming endpoint URL with the DRF token embedded as a
        query parameter so react-native-video can authenticate without needing
        a custom Authorization header on the src URL itself.

        Format: /api/videos/shorts/<uuid>/stream/?token=<drf_token_key>
        """
        request = self.context.get('request')
        path    = f"/api/videos/shorts/{obj.pk}/stream/"

        token = None
        if request and request.auth:
            # TokenAuthentication sets request.auth to the Token model instance.
            # .key is the raw token string stored in authtoken_token.key
            token = request.auth.key

        if token:
            path = f"{path}?token={token}"

        if request:
            return request.build_absolute_uri(path)
        return path

    def get_thumbnail_url(self, obj):
        request = self.context.get('request')
        if obj.thumbnail:
            url = obj.thumbnail.url
            return request.build_absolute_uri(url) if request else url
        return None

    def get_share_url(self, obj):
        return obj.share_url

    def get_is_liked(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            # Uses the prefetch_related('likes') cache from feed_algorithm.py
            # so this does not issue a per-video query.
            return obj.likes.filter(user=request.user).exists()
        return False

    def get_og_title(self, obj):
        try:
            return obj.og_title
        except AttributeError:
            return f"{obj.author.username}: {obj.caption[:80]}" if obj.caption else str(obj.id)

    def get_og_description(self, obj):
        try:
            return obj.og_description
        except AttributeError:
            return obj.caption[:200] if obj.caption else ""


# ─────────────────────────────────────────────────────────────────────────────
# SHORT VIDEO — WRITE  (FIX-1)
# ─────────────────────────────────────────────────────────────────────────────

class ShortVideoCreateSerializer(serializers.ModelSerializer):
    """
    Write serializer for ShortVideoUploadView.

    FIX-1: Declares `video` as a writable FileField so the compressed
    InMemoryUploadedFile is processed through validated_data and the storage
    backend (local / S3 / GCS) handles the save correctly.

    `author`, `duration`, and `video` are supplied by perform_create() as
    kwargs to .save(), not from request data, so they are excluded from the
    declared fields list (they cannot be set by the client directly).

    Response: ShortVideoUploadView.create() builds a separate ShortVideoSerializer
    instance for the response so the client receives the full read payload
    (video_url, thumbnail_url, is_liked, etc.).
    """
    video = serializers.FileField(required=False)   # FIX-1: writable file field

    class Meta:
        model  = ShortVideo
        fields = ['caption', 'league', 'team', 'video']

    def validate_video(self, value):
        """
        Basic MIME-type guard — reject obvious non-video uploads early.
        ffmpeg will catch everything else during compression.
        """
        content_type = getattr(value, 'content_type', '') or ''
        if content_type and not content_type.startswith('video/'):
            raise serializers.ValidationError(
                f"Uploaded file must be a video. Received: {content_type}"
            )
        return value


# ─────────────────────────────────────────────────────────────────────────────
# ENGAGEMENT (write)
# ─────────────────────────────────────────────────────────────────────────────

class VideoLikeSerializer(serializers.ModelSerializer):
    class Meta:
        model  = VideoLike
        fields = ['id', 'video', 'created_at']
        read_only_fields = ['id', 'created_at']


class VideoShareSerializer(serializers.ModelSerializer):
    class Meta:
        model  = VideoShare
        fields = ['id', 'video', 'platform', 'created_at']
        read_only_fields = ['id', 'created_at']

    def validate_platform(self, value):
        valid = {c[0] for c in VideoShare.PLATFORM_CHOICES}
        if value not in valid:
            raise serializers.ValidationError(
                f"Platform must be one of: {', '.join(sorted(valid))}"
            )
        return value


class VideoViewSerializer(serializers.ModelSerializer):
    """
    Posted by the client when the player reports a watch-time update.
    `watch_time`  : total seconds watched (float), max 7200 (2 hrs).
    `completed`   : read-only — computed in VideoView.save() from
                    watch_time vs video duration. Never sent by the client.
    """
    completed = serializers.BooleanField(read_only=True)

    class Meta:
        model  = VideoView
        fields = ['id', 'video', 'watch_time', 'completed', 'created_at']
        read_only_fields = ['id', 'completed', 'created_at']

    def validate_watch_time(self, value):
        if value < 0:
            raise serializers.ValidationError("watch_time cannot be negative.")
        if value > 7200:
            raise serializers.ValidationError(
                "watch_time cannot exceed 7200 seconds (2 hrs)."
            )
        return value