"""
ConnectDial — Views
====================
Endpoints
─────────
Feed
  GET  /api/videos/shorts/feed/                              personalised short-video feed

Upload
  POST /api/videos/shorts/upload/                            upload a new short video

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

# ── stdlib ────────────────────────────────────────────────────────────────────
import os
import subprocess
import tempfile

# ── Django ────────────────────────────────────────────────────────────────────
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.shortcuts import get_object_or_404

# ── DRF ──────────────────────────────────────────────────────────────────────
from rest_framework import generics, status
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.generics import ListAPIView
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import (
    AllowAny,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
)
from rest_framework.response import Response
from rest_framework.views import APIView

# ── Local ─────────────────────────────────────────────────────────────────────
from .feed_algorithm import get_short_video_feed
from .models import ShortVideo, VideoComment, VideoLike, VideoShare, VideoView
from .serializers import (
    ShortVideoSerializer,
    VideoCommentCreateSerializer,
    VideoCommentSerializer,
    VideoLikeSerializer,
    VideoShareSerializer,
    VideoViewSerializer,
)
from .streaming import (
    build_telegram_share_text,
    build_whatsapp_share_text,
    stream_video_response,
)

User = get_user_model()


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Helper: extract video duration with ffprobe
# ─────────────────────────────────────────────────────────────────────────────

def extract_duration(file_path: str) -> int:
    """
    Use ffprobe to read the video duration in whole seconds.
    Returns 0 if ffprobe fails or the output cannot be parsed.
    Requires: ffprobe (part of the ffmpeg package).
    Install:  sudo apt-get install ffmpeg
    """
    try:
        result = subprocess.run(
            [
                'ffprobe', '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                file_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return int(float(result.stdout.strip()))
    except Exception:
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Helper: compress with ffmpeg + -movflags +faststart (HIGH PRIORITY)
# ─────────────────────────────────────────────────────────────────────────────

def compress_video(input_path: str, output_path: str) -> None:
    """
    Re-encode the video to H.264/AAC and write the MP4 moov atom (header)
    to the START of the file using -movflags +faststart.

    WHY THIS MATTERS:
    Without +faststart, mobile players must download the entire file before
    playback begins (the moov atom sits at the end). With +faststart, the
    header is at the front, so react-native-video can start playing in ~1 s
    even over a slow connection.

    Encoding settings:
      -crf 28       → quality/size sweet spot (23 = higher quality, 28 = smaller file)
      -preset fast  → fast encoding; use 'medium' for better compression at the cost of time
      -b:a 128k     → audio bitrate
    """
    subprocess.run(
        [
            'ffmpeg', '-i', input_path,
            '-vcodec', 'libx264',
            '-crf', '28',
            '-preset', 'fast',
            '-acodec', 'aac',
            '-b:a', '128k',
            '-movflags', '+faststart',   # ← THE KEY FLAG — moov atom at file start
            '-y',                        # overwrite output without asking
            output_path,
        ],
        check=True,
        timeout=300,                     # 5-minute hard limit per video
    )


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Helper: auto-generate thumbnail from video frame at 1 s
# ─────────────────────────────────────────────────────────────────────────────

def generate_thumbnail(video_path: str) -> bytes:
    """
    Extract a single frame at the 1-second mark and return it as JPEG bytes.
    The frame is scaled to 480 px wide (height proportional).

    Returns raw JPEG bytes that can be passed directly to Django's
    FieldFile.save(name, ContentFile(bytes), save=True).
    """
    thumb_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as thumb:
            thumb_path = thumb.name

        subprocess.run(
            [
                'ffmpeg', '-i', video_path,
                '-ss', '00:00:01',       # seek to 1 second
                '-vframes', '1',         # grab exactly 1 frame
                '-vf', 'scale=480:-1',   # 480 px wide, auto height
                '-y', thumb_path,
            ],
            check=True,
            timeout=60,
        )

        with open(thumb_path, 'rb') as f:
            return f.read()
    finally:
        if thumb_path and os.path.exists(thumb_path):
            os.unlink(thumb_path)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Upload view  (uses helpers from Steps 1, 2, 3)
# ─────────────────────────────────────────────────────────────────────────────

class ShortVideoUploadView(generics.CreateAPIView):
    """
    POST /api/videos/shorts/upload/

    Accepts multipart/form-data with:
      video    (required) : video file
      caption  (optional) : text caption
      league   (optional) : league FK
      team     (optional) : team FK

    Pipeline:
      1. Write upload to a temp file.
      2. Compress with ffmpeg (-movflags +faststart) → new temp file.
      3. Extract duration from the compressed file.
      4. Save the compressed file as the model's `video` field.
      5. Auto-generate a thumbnail if none was provided.
      6. Return the full ShortVideoSerializer payload.

    Temp files are always cleaned up, even on failure.
    """
    serializer_class  = ShortVideoSerializer
    permission_classes = [IsAuthenticated]
    parser_classes     = [MultiPartParser, FormParser]

    def perform_create(self, serializer):
        video_file      = self.request.FILES.get('video')
        duration        = 0
        tmp_path        = None
        compressed_path = None

        try:
            if video_file:
                # ── 1. Write upload to temp ──────────────────────────────
                with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp:
                    for chunk in video_file.chunks():
                        tmp.write(chunk)
                    tmp_path = tmp.name

                # ── 2. Compress + +faststart ─────────────────────────────
                compressed_path = tmp_path + '_compressed.mp4'
                compress_video(tmp_path, compressed_path)

                # ── 3. Extract duration from compressed output ───────────
                duration = extract_duration(compressed_path)

                # ── 4. Re-open compressed file and hand it to the serializer
                #       so Django's storage backend saves it to GCS / local.
                with open(compressed_path, 'rb') as cf:
                    from django.core.files.uploadedfile import InMemoryUploadedFile
                    import io
                    compressed_content = cf.read()

                compressed_file = InMemoryUploadedFile(
                    file=io.BytesIO(compressed_content),
                    field_name='video',
                    name=video_file.name,
                    content_type='video/mp4',
                    size=len(compressed_content),
                    charset=None,
                )

                instance = serializer.save(
                    author=self.request.user,
                    duration=duration,
                    video=compressed_file,
                )

                # ── 5. Auto-generate thumbnail if none uploaded ──────────
                if compressed_path and not instance.thumbnail:
                    thumb_bytes = generate_thumbnail(compressed_path)
                    instance.thumbnail.save(
                        f'thumb_{instance.pk}.jpg',
                        ContentFile(thumb_bytes),
                        save=True,
                    )
            else:
                # No video file provided — save with whatever fields were sent
                serializer.save(author=self.request.user, duration=duration)

        finally:
            # Always clean up temp files
            for path in (tmp_path, compressed_path):
                if path and os.path.exists(path):
                    try:
                        os.unlink(path)
                    except OSError:
                        pass


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Feed pagination (Twitter-style LimitOffset)
# ─────────────────────────────────────────────────────────────────────────────

class ShortVideoPagination(LimitOffsetPagination):
    """
    LimitOffset pagination for the short-video feed.

    ?limit=10&offset=0  → first page
    ?limit=10&offset=10 → second page

    Response shape:
      {
        "count":    <total>,
        "next":     "<url>",
        "previous": "<url>",
        "results":  [...]
      }

    The `next` URL is what React Native's FlatList uses to fetch the next page
    (infinite scroll). Keeping default_limit at 10 keeps the initial payload
    small so the first screen renders fast.
    """
    default_limit = 10
    max_limit     = 20


class ShortVideoFeedView(ListAPIView):
    """
    GET /api/videos/shorts/feed/

    Personalised short-video feed — all videos come from our database.
    Supports videos up to 2 hours (7200 seconds).

    Query params
    ────────────
    limit        : int (default 10, max 20)
    offset       : int (default 0)  — standard LimitOffset pagination
    bypass_cache : any value → forces a fresh score computation
    """
    authentication_classes = [TokenAuthentication]
    permission_classes     = [IsAuthenticated]
    serializer_class       = ShortVideoSerializer
    pagination_class       = ShortVideoPagination   # ← STEP 4

    def get_queryset(self):
        limit  = min(
            int(self.request.query_params.get('limit', 10)),
            ShortVideoPagination.max_limit,
        )
        bypass = bool(self.request.query_params.get('bypass_cache', False))
        return get_short_video_feed(self.request.user, limit=limit, bypass_cache=bypass)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['request'] = self.request
        return ctx

    def list(self, request, *args, **kwargs):
        """
        Override list() so that:
        - If pagination is active  → returns { count, next, previous, results }
        - If pagination is skipped → falls back to { results, count }
        """
        qs   = self.get_queryset()
        page = self.paginate_queryset(list(qs))

        serializer = self.get_serializer(
            page if page is not None else qs,
            many=True,
            context={'request': request},
        )

        if page is not None:
            return self.get_paginated_response(serializer.data)

        return Response({
            'results': serializer.data,
            'count':   len(serializer.data),
        })


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
            .select_related('author')
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
        comment = serializer.save(author=request.user)

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