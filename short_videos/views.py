"""
ConnectDial — Views
====================
Endpoints
─────────
Feed
  GET  /api/videos/shorts/feed/                              personalised short-video feed

Streaming
  GET  /api/videos/shorts/<pk>/stream/                       HTTP Range-aware video stream
  GET  /api/videos/shorts/<pk>/stream/?token=<drf_token>     token via query param for native players

Engagement — Likes
  POST   /api/videos/shorts/<pk>/like/                  toggle like on/off

Engagement — Views
  POST   /api/videos/shorts/<pk>/view/                  record a watch-time event

Engagement — Shares
  POST   /api/videos/shorts/<pk>/share/                 record external share event
  POST   /api/videos/shorts/<pk>/reshare/               in-app reshare

Comments
  GET    /api/videos/shorts/<pk>/comments/              list top-level comments
  POST   /api/videos/shorts/<pk>/comments/              create a comment
  GET    /api/videos/shorts/<pk>/comments/<id>/replies/ list replies
  PATCH  /api/videos/comments/<id>/                     edit own comment
  DELETE /api/videos/comments/<id>/                     delete own comment
"""

from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model

from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token

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
from .streaming import (
    stream_video_response,
    build_whatsapp_share_text,
    build_telegram_share_text,
)

User = get_user_model()


# ─────────────────────────────────────────────────────────────────────────────
# FEED
# ─────────────────────────────────────────────────────────────────────────────

class ShortVideoFeedView(ListAPIView):
    """
    GET /api/videos/shorts/feed/

    Personalised short-video feed — all videos come from our database.
    Supports videos up to 2 hours (7200 seconds).

    Query params
    ────────────
    limit        : int (default 20, max 50)
    bypass_cache : any value → forces a fresh score computation
    """
    authentication_classes = [TokenAuthentication]
    permission_classes     = [IsAuthenticated]
    serializer_class       = ShortVideoSerializer

    def get_queryset(self):
        limit  = min(int(self.request.query_params.get('limit', 20)), 50)
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
    GET /api/videos/shorts/<pk>/stream/
    GET /api/videos/shorts/<pk>/stream/?token=<drf_token_key>

    HTTP Range-aware video streaming.
    Supports seeking, progressive playback, and resume after network drops.

    Authentication
    ──────────────
    Standard: Authorization: Token <key> header (handled by TokenAuthentication).

    Query-param fallback: ?token=<key>
    react-native-video cannot attach custom headers to a video src URL.
    If no Authorization header is present, we manually look up the token from
    the query param and authenticate the user that way.

    IMPORTANT: permission_classes is intentionally empty here. DRF's permission
    check runs before our view code, so we cannot use IsAuthenticated — it would
    reject ?token= requests before our fallback logic runs. Authentication is
    enforced manually at the bottom of this method instead.
    """
    authentication_classes = [TokenAuthentication]
    permission_classes     = []   # Auth enforced manually below — see docstring

    def get(self, request, pk):
        user = request.user

        # ── Query-param token fallback for react-native-video ─────────────
        # If DRF's TokenAuthentication didn't resolve a user from the
        # Authorization header, try the ?token= query param.
        if not user or not user.is_authenticated:
            token_key = request.query_params.get('token', '').strip()
            if token_key:
                try:
                    token_obj = Token.objects.select_related('user').get(key=token_key)
                    user = token_obj.user
                except Token.DoesNotExist:
                    return Response(
                        {'detail': 'Invalid or expired token.'},
                        status=status.HTTP_401_UNAUTHORIZED,
                    )

        # ── Final auth gate ───────────────────────────────────────────────
        if not user or not user.is_authenticated:
            return Response(
                {'detail': 'Authentication credentials were not provided.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        video = get_object_or_404(ShortVideo, pk=pk)
        return stream_video_response(request, video)


# ─────────────────────────────────────────────────────────────────────────────
# LIKES (toggle)
# ─────────────────────────────────────────────────────────────────────────────

class VideoLikeToggleView(APIView):
    """
    POST /api/videos/shorts/<pk>/like/
    Toggles like. Returns { liked, likes_count }.
    The cached_likes counter is kept in sync by signals.py.
    """
    authentication_classes = [TokenAuthentication]
    permission_classes     = [IsAuthenticated]

    def post(self, request, pk):
        video = get_object_or_404(ShortVideo, pk=pk)
        like, created = VideoLike.objects.get_or_create(user=request.user, video=video)
        if created:
            video.refresh_from_db(fields=['cached_likes'])
            return Response(
                {'liked': True, 'likes_count': video.cached_likes},
                status=status.HTTP_201_CREATED,
            )
        # Already liked — toggle off
        like.delete()
        video.refresh_from_db(fields=['cached_likes'])
        return Response(
            {'liked': False, 'likes_count': video.cached_likes},
            status=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        video = get_object_or_404(ShortVideo, pk=pk)
        deleted, _ = VideoLike.objects.filter(user=request.user, video=video).delete()
        video.refresh_from_db(fields=['cached_likes'])
        if deleted:
            return Response(
                {'liked': False, 'likes_count': video.cached_likes},
                status=status.HTTP_204_NO_CONTENT,
            )
        return Response({'detail': 'Not liked.'}, status=status.HTTP_404_NOT_FOUND)


# ─────────────────────────────────────────────────────────────────────────────
# VIEWS / WATCH TIME
# ─────────────────────────────────────────────────────────────────────────────

class VideoViewRecordView(APIView):
    """
    POST /api/videos/shorts/<pk>/view/
    Body: { "watch_time": <seconds_float> }

    Records one view event. The player calls this when the user leaves,
    pauses, or completes the video. Supports watch_time up to 7200s (2 hrs).
    """
    authentication_classes = [TokenAuthentication]
    permission_classes     = [IsAuthenticated]

    def post(self, request, pk):
        video = get_object_or_404(ShortVideo, pk=pk)
        serializer = VideoViewSerializer(
            data={**request.data, 'video': str(video.pk)}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(user=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────────────────────────────────────
# SHARES — external
# ─────────────────────────────────────────────────────────────────────────────

class VideoShareRecordView(APIView):
    """
    POST /api/videos/shorts/<pk>/share/
    Body: { "platform": "whatsapp" }  (see VideoShare.PLATFORM_CHOICES)
    Records a share event and returns the platform-specific share payload.
    """
    authentication_classes = [TokenAuthentication]
    permission_classes     = [IsAuthenticated]

    def post(self, request, pk):
        video = get_object_or_404(ShortVideo, pk=pk)
        serializer = VideoShareSerializer(
            data={**request.data, 'video': str(video.pk)}
        )
        serializer.is_valid(raise_exception=True)
        share = serializer.save(user=request.user)

        platform = share.platform
        payload  = {
            **serializer.data,
            'share_url':      video.share_url,
            'og_title':       video.og_title,
            'og_description': video.og_description,
            'thumbnail_url': (
                request.build_absolute_uri(video.thumbnail.url)
                if video.thumbnail else None
            ),
        }

        if platform == 'whatsapp':
            text = build_whatsapp_share_text(video)
            payload['text']         = text
            payload['whatsapp_url'] = f"https://wa.me/?text={text}"

        elif platform == 'telegram':
            text = build_telegram_share_text(video)
            payload['text']         = text
            payload['telegram_url'] = (
                f"https://t.me/share/url?url={video.share_url}"
                f"&text={video.og_title}"
            )

        elif platform == 'twitter':
            payload['twitter_url'] = (
                f"https://twitter.com/intent/tweet"
                f"?url={video.share_url}&text={video.og_title}"
            )

        else:
            payload['share_text'] = video.share_url

        return Response(payload, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────────────────────────────────────
# RESHARE — in-app
# ─────────────────────────────────────────────────────────────────────────────

class VideoReshareView(APIView):
    """
    POST /api/videos/shorts/<pk>/reshare/
    In-app reshare — appears on the resharer's profile feed.
    Calling again undoes the reshare (toggle).
    """
    authentication_classes = [TokenAuthentication]
    permission_classes     = [IsAuthenticated]

    def post(self, request, pk):
        video = get_object_or_404(ShortVideo, pk=pk)

        existing = VideoShare.objects.filter(
            user=request.user,
            video=video,
            platform='other',
        ).first()

        if existing:
            existing.delete()
            return Response({'reshared': False}, status=status.HTTP_200_OK)

        VideoShare.objects.create(
            user=request.user,
            video=video,
            platform='other',
        )
        return Response({'reshared': True}, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────────────────────────────────────
# COMMENTS
# ─────────────────────────────────────────────────────────────────────────────

class VideoCommentListCreateView(APIView):
    """
    GET  /api/videos/shorts/<pk>/comments/   list top-level comments
    POST /api/videos/shorts/<pk>/comments/   create a comment

    Body fields:
      body    (required) : comment text, may include @username tokens
      parent  (optional) : UUID of the comment being replied to
    """
    authentication_classes = [TokenAuthentication]
    permission_classes     = [IsAuthenticatedOrReadOnly]

    def get(self, request, pk):
        video    = get_object_or_404(ShortVideo, pk=pk)
        comments = (
            VideoComment.objects
            .filter(video=video, parent__isnull=True)
            .select_related('author')           # 'author' is the Python attr; db_column='user_id'
            .prefetch_related('mentions__user', 'replies')
            .order_by('created_at')
        )
        serializer = VideoCommentSerializer(
            comments, many=True, context={'request': request}
        )
        return Response(serializer.data)

    def post(self, request, pk):
        video = get_object_or_404(ShortVideo, pk=pk)
        serializer = VideoCommentCreateSerializer(
            data={**request.data, 'video': str(video.pk)},
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        comment = serializer.save(author=request.user)  # passes as FK kwarg → user_id col

        read_serializer = VideoCommentSerializer(
            comment, context={'request': request}
        )
        return Response(read_serializer.data, status=status.HTTP_201_CREATED)


class CommentRepliesListView(ListAPIView):
    """
    GET /api/videos/shorts/<pk>/comments/<comment_pk>/replies/
    """
    authentication_classes = [TokenAuthentication]
    permission_classes     = [IsAuthenticatedOrReadOnly]
    serializer_class       = VideoCommentSerializer

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
    PATCH  /api/videos/comments/<pk>/  — edit own comment
    DELETE /api/videos/comments/<pk>/  — delete own comment
    """
    authentication_classes = [TokenAuthentication]
    permission_classes     = [IsAuthenticated]

    def _get_own_comment(self, request, pk):
        comment = get_object_or_404(VideoComment, pk=pk)
        # author_id resolves to the user_id column via db_column
        if comment.author_id != request.user.pk:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You can only edit or delete your own comments.")
        return comment

    def patch(self, request, pk):
        comment    = self._get_own_comment(request, pk)
        serializer = VideoCommentCreateSerializer(
            comment, data=request.data, partial=True,
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