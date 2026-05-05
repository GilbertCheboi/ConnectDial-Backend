"""
ConnectDial — Views
====================
Endpoints
─────────
Feed
  GET  /api/shorts/feed/                   personalised short-video feed

Streaming
  GET  /api/shorts/<pk>/stream/            HTTP Range-aware video stream

Engagement — Likes
  POST   /api/shorts/<pk>/like/            toggle like on/off
  DELETE /api/shorts/<pk>/like/            (same, both toggle)

Engagement — Views
  POST   /api/shorts/<pk>/view/            record a watch-time event

Engagement — Shares
  POST   /api/shorts/<pk>/share/           record a share event

Comments
  GET    /api/shorts/<pk>/comments/        list top-level comments
  POST   /api/shorts/<pk>/comments/        create a comment (supports @mentions)
  GET    /api/shorts/<pk>/comments/<id>/replies/   list replies to a comment
  PATCH  /api/comments/<id>/              edit own comment
  DELETE /api/comments/<id>/              delete own comment
"""

from django.db import IntegrityError
from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.views import APIView

from .feed_algorithm import get_short_video_feed
from .models import ShortVideo, VideoComment, VideoLike, VideoShare, VideoView
from .serializers import (
    ShortVideoSerializer,
    VideoCommentSerializer,
    VideoCommentCreateSerializer,
    VideoLikeSerializer,
    VideoShareSerializer,
    VideoViewSerializer,
)
from .streaming import stream_video_response


# ─────────────────────────────────────────────────────────────────────────────
# FEED
# ─────────────────────────────────────────────────────────────────────────────

class ShortVideoFeedView(ListAPIView):
    """
    Personalised short-video feed.

    Query params
    ────────────
    limit        : int (default 20, max 50)
    bypass_cache : any value → forces a fresh score computation

    Content comes entirely from our database ranked by the feed algorithm.
    No external video links (YouTube etc.) are served here.
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = ShortVideoSerializer

    def get_queryset(self):
        limit = min(int(self.request.query_params.get('limit', 20)), 50)
        bypass = bool(self.request.query_params.get('bypass_cache', False))
        return get_short_video_feed(self.request.user, limit=limit, bypass_cache=bypass)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['request'] = self.request
        return ctx


# ─────────────────────────────────────────────────────────────────────────────
# STREAMING
# ─────────────────────────────────────────────────────────────────────────────

class ShortVideoStreamView(APIView):
    """
    HTTP Range-aware video streaming.
    Supports seeking, progressive playback and resume on reconnect.
    In production, redirects to a pre-signed S3/GCS URL (see streaming.py).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        video = get_object_or_404(ShortVideo, pk=pk)
        return stream_video_response(request, video)


# ─────────────────────────────────────────────────────────────────────────────
# LIKES  (toggle)
# ─────────────────────────────────────────────────────────────────────────────

class VideoLikeToggleView(APIView):
    """
    POST or DELETE → toggles a like on the given video.
    Returns 201 when liked, 204 when unliked.
    The cached_likes counter is kept in sync by signals.py.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        video = get_object_or_404(ShortVideo, pk=pk)
        like, created = VideoLike.objects.get_or_create(user=request.user, video=video)
        if created:
            return Response({'liked': True}, status=status.HTTP_201_CREATED)
        # Already liked — treat as unlike toggle
        like.delete()
        return Response({'liked': False}, status=status.HTTP_200_OK)

    def delete(self, request, pk):
        video = get_object_or_404(ShortVideo, pk=pk)
        deleted, _ = VideoLike.objects.filter(user=request.user, video=video).delete()
        if deleted:
            return Response({'liked': False}, status=status.HTTP_204_NO_CONTENT)
        return Response({'detail': 'Not liked.'}, status=status.HTTP_404_NOT_FOUND)


# ─────────────────────────────────────────────────────────────────────────────
# VIEWS / WATCH TIME
# ─────────────────────────────────────────────────────────────────────────────

class VideoViewRecordView(APIView):
    """
    POST body: { "watch_time": <seconds_float> }
    Records one view event.  The player should call this when the user
    leaves / pauses / completes the video.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        video = get_object_or_404(ShortVideo, pk=pk)
        serializer = VideoViewSerializer(data={**request.data, 'video': video.pk})
        serializer.is_valid(raise_exception=True)
        serializer.save(user=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────────────────────────────────────
# SHARES
# ─────────────────────────────────────────────────────────────────────────────

class VideoShareRecordView(APIView):
    """
    POST body: { "platform": "whatsapp" }  (see VideoShare.PLATFORM_CHOICES)
    Records a share event and returns the appropriate share text.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from .streaming import build_whatsapp_share_text, build_telegram_share_text

        video = get_object_or_404(ShortVideo, pk=pk)
        serializer = VideoShareSerializer(data={**request.data, 'video': video.pk})
        serializer.is_valid(raise_exception=True)
        share = serializer.save(user=request.user)

        # Build share text for the client
        platform = share.platform
        if platform == 'whatsapp':
            share_text = build_whatsapp_share_text(video)
        elif platform == 'telegram':
            share_text = build_telegram_share_text(video)
        else:
            share_text = video.share_url

        return Response(
            {**serializer.data, 'share_text': share_text},
            status=status.HTTP_201_CREATED,
        )


# ─────────────────────────────────────────────────────────────────────────────
# COMMENTS
# ─────────────────────────────────────────────────────────────────────────────

class VideoCommentListCreateView(APIView):
    """
    GET  → list top-level comments for a video (paginated, oldest first).
    POST → create a new comment or reply.

    Creating a comment
    ──────────────────
    Body fields:
      body    (required) : comment text, may include @username tokens
      parent  (optional) : UUID of the comment being replied to

    @mention resolution
    ───────────────────
    @username tokens in `body` are automatically resolved to real users by
    the `comment_saved` signal in signals.py.  The client does NOT need to
    pass a separate list of user IDs.

    Example body:
      "Great goal @john.doe! @jane_smith what do you think?"

    Both @john.doe and @jane_smith will receive a notification if they exist.
    """
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get(self, request, pk):
        video    = get_object_or_404(ShortVideo, pk=pk)
        comments = (
            VideoComment.objects
            .filter(video=video, parent__isnull=True)   # top-level only
            .select_related('author')
            .prefetch_related('mentions__user', 'replies')
            .order_by('created_at')
        )
        serializer = VideoCommentSerializer(comments, many=True, context={'request': request})
        return Response(serializer.data)

    def post(self, request, pk):
        video = get_object_or_404(ShortVideo, pk=pk)
        serializer = VideoCommentCreateSerializer(
            data={**request.data, 'video': str(video.pk)},
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        comment = serializer.save(author=request.user)

        # Return the full read representation including resolved mentions
        read_serializer = VideoCommentSerializer(
            comment,
            context={'request': request},
        )
        return Response(read_serializer.data, status=status.HTTP_201_CREATED)


class CommentRepliesListView(ListAPIView):
    """
    GET /api/shorts/<pk>/comments/<comment_id>/replies/
    Lists direct replies to a specific comment.
    """
    permission_classes    = [IsAuthenticatedOrReadOnly]
    serializer_class      = VideoCommentSerializer

    def get_queryset(self):
        video_pk   = self.kwargs['pk']
        comment_pk = self.kwargs['comment_pk']
        return (
            VideoComment.objects
            .filter(video_id=video_pk, parent_id=comment_pk)
            .select_related('author')
            .prefetch_related('mentions__user')
            .order_by('created_at')
        )


class CommentDetailView(APIView):
    """
    PATCH  /api/comments/<pk>/   — edit own comment (updates @mentions too)
    DELETE /api/comments/<pk>/   — delete own comment
    """
    permission_classes = [IsAuthenticated]

    def _get_own_comment(self, request, pk):
        comment = get_object_or_404(VideoComment, pk=pk)
        if comment.author_id != request.user.pk:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You can only edit or delete your own comments.")
        return comment

    def patch(self, request, pk):
        comment    = self._get_own_comment(request, pk)
        serializer = VideoCommentCreateSerializer(
            comment,
            data=request.data,
            partial=True,
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()

        read_serializer = VideoCommentSerializer(updated, context={'request': request})
        return Response(read_serializer.data)

    def delete(self, request, pk):
        comment = self._get_own_comment(request, pk)
        comment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)