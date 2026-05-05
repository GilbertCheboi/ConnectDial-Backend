"""
ConnectDial — Serializers
==========================
Covers:
  - ShortVideoSerializer      : full video representation for the feed
  - VideoCommentSerializer    : comment with nested mentions + reply count
  - CommentMentionSerializer  : lightweight user mention representation
  - VideoCommentCreateSerializer : write-only serializer for creating comments
  - VideoLikeSerializer       : like toggle
  - VideoShareSerializer      : share event
  - VideoViewSerializer       : view / watch-time recording
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
    """Minimal user representation used inside comment mentions."""
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
    """
    Read serializer for a comment.
    - `author_username`  : poster's handle
    - `mentions`         : list of @tagged users (resolved from CommentMention)
    - `reply_count`      : how many direct replies this comment has
    - `parent`           : UUID of parent comment (null for top-level)
    """
    author_username = serializers.CharField(source='author.username', read_only=True)
    mentions        = CommentMentionSerializer(many=True, read_only=True)
    reply_count     = serializers.SerializerMethodField()

    class Meta:
        model  = VideoComment
        fields = [
            'id',
            'video',
            'author_username',
            'parent',
            'body',
            'mentions',
            'reply_count',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_reply_count(self, obj):
        return obj.replies.count()


class VideoCommentCreateSerializer(serializers.ModelSerializer):
    """
    Write serializer for creating / updating a comment.

    The `body` field is plain text that may contain @username tokens.
    Mention resolution happens in signals.py after save — the client does
    NOT need to pass a separate `mentioned_users` list.

    On creation the view must inject `author` and `video` from the request
    context before saving.
    """
    class Meta:
        model  = VideoComment
        fields = ['id', 'video', 'parent', 'body']
        read_only_fields = ['id']

    def validate_body(self, value):
        if not value.strip():
            raise serializers.ValidationError("Comment body cannot be empty.")
        return value

    def validate_parent(self, value):
        """
        Enforce max one level of nesting: a reply cannot itself be a parent.
        """
        if value and value.parent_id is not None:
            raise serializers.ValidationError(
                "Replies to replies are not supported. Tag the user with @mention instead."
            )
        return value

    def create(self, validated_data):
        # `author` is injected by the view via `perform_create`
        return super().create(validated_data)


# ─────────────────────────────────────────────────────────────────────────────
# SHORT VIDEO
# ─────────────────────────────────────────────────────────────────────────────

class ShortVideoSerializer(serializers.ModelSerializer):
    """
    Feed serializer for ShortVideo.

    All count fields come from the denormalised cached_* columns
    (annotated in the queryset by the feed algorithm / utils).
    They are read-only — clients must use the dedicated like/comment/share
    endpoints to mutate them.

    `video_url` exposes the streaming endpoint rather than a raw file path.
    `duration_display` is human-readable (e.g. "1:23" or "1:02:45").
    """
    author_username  = serializers.CharField(source='author.username', read_only=True)
    league_name      = serializers.CharField(source='league.name',     read_only=True, default=None)
    team_name        = serializers.CharField(source='team.name',       read_only=True, default=None)

    # Annotated in queryset by get_short_video_feed / _preserve_order_queryset
    likes_count      = serializers.IntegerField(read_only=True)
    comments_count   = serializers.IntegerField(read_only=True)
    shares_count     = serializers.IntegerField(read_only=True)
    views_count      = serializers.IntegerField(read_only=True, default=0)

    duration_display = serializers.CharField(read_only=True)

    # Absolute streaming URL — built from request so it's always absolute
    video_url        = serializers.SerializerMethodField()
    share_url        = serializers.SerializerMethodField()

    class Meta:
        model  = ShortVideo
        fields = [
            'id',
            'author_username',
            'video_url',
            'thumbnail',
            'caption',
            'league_name',
            'team_name',
            'duration',
            'duration_display',
            'likes_count',
            'comments_count',
            'shares_count',
            'views_count',
            'share_url',
            'created_at',
        ]

    def get_video_url(self, obj):
        """
        Returns the streaming endpoint URL:
          /api/shorts/<uuid>/stream/
        This lets the mobile player use Range requests via streaming.py.
        """
        request = self.context.get('request')
        path    = f"/api/shorts/{obj.pk}/stream/"
        if request:
            return request.build_absolute_uri(path)
        return path

    def get_share_url(self, obj):
        return obj.share_url


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
            raise serializers.ValidationError(f"Platform must be one of: {', '.join(sorted(valid))}")
        return value


class VideoViewSerializer(serializers.ModelSerializer):
    """
    Posted by the client when the player reports a watch-time update.
    `watch_time` is total seconds watched (float).
    """
    class Meta:
        model  = VideoView
        fields = ['id', 'video', 'watch_time', 'created_at']
        read_only_fields = ['id', 'created_at']

    def validate_watch_time(self, value):
        if value < 0:
            raise serializers.ValidationError("watch_time cannot be negative.")
        return value