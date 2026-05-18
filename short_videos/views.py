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

Fixes applied
─────────────
  FIX-1  ShortVideoUploadView now uses ShortVideoCreateSerializer (writable video
         field) instead of the read-only ShortVideoSerializer, so the video file
         goes through proper validation rather than being passed as a raw kwarg.

  FIX-2  VideoReshareView now uses platform='reshare' instead of platform='other'.
         Using 'other' caused any external share with platform='other' to
         accidentally toggle the in-app reshare off on the next call.
         'reshare' is a dedicated choice in VideoShare.PLATFORM_CHOICES.

  FIX-3  VideoLikeToggleView.delete() now returns HTTP 200 with a JSON body
         instead of HTTP 204 No Content. 204 must have no body; returning one
         causes some clients to silently drop the response data.

  FIX-4  VideoShareRecordView WhatsApp, Telegram, and Twitter share URLs now
         URL-encode the text/title parameters via urllib.parse.quote so
         multi-line share text and special characters don't break the URLs.

  FIX-5  ShortVideoFeedView.get_queryset() no longer passes 'limit' to
         get_short_video_feed(). The feed algorithm now always fetches
         FEED_FETCH_SIZE (200) candidates; LimitOffsetPagination does all
         slicing. This prevents the paginator from running out of rows on
         page 2+ because the algorithm had already sliced to page-1 size.

  FIX-6  compress_video timeout raised from 300 s to 7 200 s (2 hrs) to match
         the maximum supported video length. A 2-hr upload can easily exceed
         5 minutes of encoding time.
"""

# ── stdlib ────────────────────────────────────────────────────────────────────
import io
import os
import subprocess
import tempfile
from urllib.parse import quote  # FIX-4

# ── Django ────────────────────────────────────────────────────────────────────
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.shortcuts import get_object_or_404

# ── DRF ──────────────────────────────────────────────────────────────────────
from rest_framework import generics, status
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.generics import ListAPIView
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import (
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
)
from rest_framework.response import Response
from rest_framework.views import APIView

# ── Local ─────────────────────────────────────────────────────────────────────
from .feed_algorithm import get_short_video_feed, FEED_FETCH_SIZE
from .models import ShortVideo, VideoComment, VideoLike, VideoShare, VideoView
from .serializers import (
    ShortVideoSerializer,
    ShortVideoCreateSerializer,        # FIX-1
    VideoCommentCreateSerializer,
    VideoCommentSerializer,
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
# HELPERS — ffmpeg / ffprobe
# ─────────────────────────────────────────────────────────────────────────────

def extract_duration(file_path: str) -> int:
    """
    Use ffprobe to read the video duration in whole seconds.
    Returns 0 if ffprobe is unavailable or the output cannot be parsed.
    Install: sudo apt-get install ffmpeg
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


def compress_video(input_path: str, output_path: str) -> None:
    """
    Re-encode to H.264/AAC and write the MP4 moov atom to the START of the
    file using -movflags +faststart so react-native-video can begin playback
    in ~1 s without downloading the whole file first.

    FIX-6: Timeout raised to 7 200 s (2 hrs) to match the maximum supported
    video length. 2-hr 1080p content can easily exceed 5 minutes of encoding.
    """
    subprocess.run(
        [
            'ffmpeg', '-i', input_path,
            '-vcodec', 'libx264',
            '-crf', '28',
            '-preset', 'fast',
            '-acodec', 'aac',
            '-b:a', '128k',
            '-movflags', '+faststart',
            '-y',
            output_path,
        ],
        check=True,
        timeout=7200,   # FIX-6: was 300 — far too short for 2-hr videos
    )


def generate_thumbnail(video_path: str) -> bytes:
    """
    Extract a single frame at the 1-second mark as JPEG bytes (480 px wide).
    Returns raw bytes suitable for ContentFile / FieldFile.save().
    """
    thumb_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as thumb:
            thumb_path = thumb.name

        subprocess.run(
            [
                'ffmpeg', '-i', video_path,
                '-ss', '00:00:01',
                '-vframes', '1',
                '-vf', 'scale=480:-1',
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
# UPLOAD
# ─────────────────────────────────────────────────────────────────────────────

class ShortVideoUploadView(generics.CreateAPIView):
    """
    POST /api/videos/shorts/upload/

    Accepts multipart/form-data:
      video    (required) : video file
      caption  (optional) : text caption
      league   (optional) : league FK
      team     (optional) : team FK

    Pipeline:
      1. Write upload to a temp file.
      2. Compress with ffmpeg (-movflags +faststart) → new temp file.
      3. Extract duration from the compressed file.
      4. Save the compressed file via ShortVideoCreateSerializer.
      5. Auto-generate a thumbnail if none was provided.
      6. Return the full ShortVideoSerializer read payload.

    FIX-1: Uses ShortVideoCreateSerializer (writable video field) instead of
    the read-only ShortVideoSerializer. The compressed InMemoryUploadedFile is
    passed through the serializer's validated_data so the storage backend
    (local / S3 / GCS) saves it correctly and any per-field validation runs.
    """
    # FIX-1: write with the create serializer; read response built separately
    serializer_class   = ShortVideoCreateSerializer
    permission_classes = [IsAuthenticated]
    parser_classes     = [MultiPartParser, FormParser]

    def create(self, request, *args, **kwargs):
        """
        Override create() so we can return the full read serializer payload
        (with video_url, thumbnail_url, etc.) rather than the write payload.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = self.perform_create(serializer)
        read_serializer = ShortVideoSerializer(
            instance, context={'request': request}
        )
        return Response(read_serializer.data, status=status.HTTP_201_CREATED)

    def perform_create(self, serializer):
        video_file      = self.request.FILES.get('video')
        duration        = 0
        tmp_path        = None
        compressed_path = None

        try:
            if video_file:
                # 1. Write upload to temp
                with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp:
                    for chunk in video_file.chunks():
                        tmp.write(chunk)
                    tmp_path = tmp.name

                # 2. Compress + +faststart
                compressed_path = tmp_path + '_compressed.mp4'
                compress_video(tmp_path, compressed_path)

                # 3. Extract duration from compressed output
                duration = extract_duration(compressed_path)

                # 4. Build InMemoryUploadedFile from compressed bytes and save
                #    via the serializer so the storage backend handles the path.
                with open(compressed_path, 'rb') as cf:
                    compressed_content = cf.read()

                compressed_file = InMemoryUploadedFile(
                    file=io.BytesIO(compressed_content),
                    field_name='video',
                    name=video_file.name,
                    content_type='video/mp4',
                    size=len(compressed_content),
                    charset=None,
                )

                # FIX-1: pass video= through validated_data, not as a raw kwarg
                # to Model.save(); this goes through the serializer field so
                # any storage-backend hooks (S3 upload, path generation) run.
                instance = serializer.save(
                    author=self.request.user,
                    duration=duration,
                    video=compressed_file,
                )

                # 5. Auto-generate thumbnail if none was uploaded
                if compressed_path and not instance.thumbnail:
                    try:
                        thumb_bytes = generate_thumbnail(compressed_path)
                        instance.thumbnail.save(
                            f'thumb_{instance.pk}.jpg',
                            ContentFile(thumb_bytes),
                            save=True,
                        )
                    except Exception:
                        # Thumbnail generation is non-fatal
                        pass

            else:
                # No video file — save metadata fields only
                instance = serializer.save(
                    author=self.request.user,
                    duration=duration,
                )

            return instance

        finally:
            for path in (tmp_path, compressed_path):
                if path and os.path.exists(path):
                    try:
                        os.unlink(path)
                    except OSError:
                        pass


# ─────────────────────────────────────────────────────────────────────────────
# FEED PAGINATION
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

    FIX-5: The feed algorithm now fetches FEED_FETCH_SIZE candidates (default
    200) rather than page-size candidates. This class does all slicing, so
    page 2+ gets real results instead of an empty list.
    """
    default_limit = 10
    max_limit     = 20


class ShortVideoFeedView(ListAPIView):
    """
    GET /api/videos/shorts/feed/

    Personalised short-video feed.

    Query params
    ────────────
    limit        : int (default 10, max 20)
    offset       : int (default 0)
    bypass_cache : any value → forces a fresh score computation

    FIX-5: get_queryset() no longer passes `limit` to get_short_video_feed().
    The algorithm always returns FEED_FETCH_SIZE scored candidates; the
    paginator slices them. Previously the algorithm sliced to page size first,
    so offset=10 always returned 0 rows.
    """
    authentication_classes = [TokenAuthentication]
    permission_classes     = [IsAuthenticated]
    serializer_class       = ShortVideoSerializer
    pagination_class       = ShortVideoPagination

    def get_queryset(self):
        bypass = bool(self.request.query_params.get('bypass_cache', False))
        # FIX-5: do NOT pass limit here — paginator slices the full scored list
        return get_short_video_feed(self.request.user, bypass_cache=bypass)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['request'] = self.request
        return ctx

    def list(self, request, *args, **kwargs):
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

    HTTP Range-aware video streaming. Supports seeking, progressive playback,
    and resume after network drops.

    Authentication
    ──────────────
    Standard: Authorization: Token <key> header (TokenAuthentication).

    Query-param fallback: ?token=<key>
    react-native-video cannot attach custom headers to a video src URL, so the
    serializer embeds the token as a query param. We look it up manually here.

    permission_classes is intentionally empty — DRF permission checks run
    before view code, so IsAuthenticated would reject ?token= requests before
    our fallback logic can run. Auth is enforced manually below.
    """
    authentication_classes = [TokenAuthentication]
    permission_classes     = []

    def get(self, request, pk):
        user = request.user

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
    POST   /api/videos/shorts/<pk>/like/  — toggle like on/off
    DELETE /api/videos/shorts/<pk>/like/  — explicit unlike

    Returns { liked: bool, likes_count: int }.
    cached_likes is kept in sync by signals.py.
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
        """
        Explicit DELETE unlike.
        FIX-3: Returns HTTP 200 with JSON body instead of 204 No Content.
        HTTP 204 must have no response body; returning one causes some clients
        to silently drop the data.
        """
        video = get_object_or_404(ShortVideo, pk=pk)
        deleted, _ = VideoLike.objects.filter(user=request.user, video=video).delete()
        video.refresh_from_db(fields=['cached_likes'])
        if deleted:
            return Response(               # FIX-3: was HTTP_204_NO_CONTENT
                {'liked': False, 'likes_count': video.cached_likes},
                status=status.HTTP_200_OK,
            )
        return Response({'detail': 'Not liked.'}, status=status.HTTP_404_NOT_FOUND)


# ─────────────────────────────────────────────────────────────────────────────
# VIEWS / WATCH TIME
# ─────────────────────────────────────────────────────────────────────────────

class VideoViewRecordView(APIView):
    """
    POST /api/videos/shorts/<pk>/view/
    Body: { "watch_time": <seconds_float> }

    Records one view event. Supports watch_time up to 7200 s (2 hrs).
    `completed` is computed server-side in VideoView.save().
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

    Records an external share event and returns platform-specific share URLs.

    FIX-4: WhatsApp, Telegram, and Twitter URL parameters are now properly
    URL-encoded via urllib.parse.quote so multi-line share text and special
    characters (emoji, &, #, etc.) don't break the resulting URLs.
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
            # FIX-4: was f"...?text={text}" — unencoded multi-line string
            payload['whatsapp_url'] = f"https://wa.me/?text={quote(text)}"

        elif platform == 'telegram':
            text = build_telegram_share_text(video)
            payload['text']         = text
            # FIX-4: encode both url and text params
            payload['telegram_url'] = (
                f"https://t.me/share/url"
                f"?url={quote(video.share_url, safe='')}"
                f"&text={quote(video.og_title, safe='')}"
            )

        elif platform == 'twitter':
            # FIX-4: encode url and text params
            payload['twitter_url'] = (
                f"https://twitter.com/intent/tweet"
                f"?url={quote(video.share_url, safe='')}"
                f"&text={quote(video.og_title, safe='')}"
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

    In-app reshare toggle — appears on the resharer's profile feed.
    Calling again undoes the reshare.

    FIX-2: Now uses platform='reshare' (a dedicated PLATFORM_CHOICES entry in
    models.py) instead of platform='other'. The old code used 'other', which
    is also the catch-all for any external share that doesn't match a known
    platform. A user who did an external 'other' share would accidentally have
    their reshare toggled off the next time they hit this endpoint.
    """
    authentication_classes = [TokenAuthentication]
    permission_classes     = [IsAuthenticated]

    # The dedicated platform value — matches VideoShare.PLATFORM_CHOICES
    RESHARE_PLATFORM = 'reshare'

    def post(self, request, pk):
        video = get_object_or_404(ShortVideo, pk=pk)

        existing = VideoShare.objects.filter(
            user=request.user,
            video=video,
            platform=self.RESHARE_PLATFORM,   # FIX-2: was 'other'
        ).first()

        if existing:
            existing.delete()
            return Response({'reshared': False}, status=status.HTTP_200_OK)

        VideoShare.objects.create(
            user=request.user,
            video=video,
            platform=self.RESHARE_PLATFORM,   # FIX-2: was 'other'
        )
        return Response({'reshared': True}, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────────────────────────────────────
# COMMENTS
# ─────────────────────────────────────────────────────────────────────────────

class VideoCommentListCreateView(APIView):
    """
    GET  /api/videos/shorts/<pk>/comments/   list top-level comments
    POST /api/videos/shorts/<pk>/comments/   create a comment

    POST body fields:
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
            .select_related('author', 'author__profile')
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
            .select_related('author', 'author__profile')
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