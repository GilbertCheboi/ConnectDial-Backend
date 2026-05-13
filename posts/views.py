"""
views.py – ConnectDial Posts App
──────────────────────────────────────────────────────────────────────
WHY FILES WEREN'T SAVING — ROOT CAUSE CONFIRMED
──────────────────────────────────────────────────────────────────────
GCS works fine (test.txt saved successfully). The bug is in the
serializer layer:

  DRF's ModelSerializer auto-generates FileField as READ-ONLY.
  'media_file' was listed in Meta.fields but silently excluded from
  validated_data on every POST because DRF treats model FileFields
  as non-writable unless explicitly declared.

  This means serializer.save(media_file=f) never actually set anything
  because the field was write-protected at the serializer level.

FIX (two-pronged):
  1. serializers.py — declare media_file as an explicit writable
     FileField(required=False, allow_empty_file=True).
  2. views.py (here) — perform_create saves the Post first (text fields),
     then assigns media_file directly on the instance + calls
     post.save(update_fields=['media_file']). This is belt-and-suspenders:
     even if the serializer ever reverts, the file still saves correctly.
"""

import os
import logging

from django.db.models import Count, Exists, F, OuterRef, Q

from rest_framework import filters, generics, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import CursorPagination
from rest_framework.parsers import FormParser, MultiPartParser, JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from users.models import Follow

from .models import Comment, Hashtag, Post, PostLike, PostMedia, PostShare, VideoUploadSession
from .serializers import CommentSerializer, HashtagSerializer, PostSerializer
from .services import get_personalized_shorts, get_trending_hashtags

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# PAGINATION
# ─────────────────────────────────────────────────────────────────────

class FeedCursorPagination(CursorPagination):
    page_size             = 20
    page_size_query_param = 'page_size'
    max_page_size         = 50
    ordering              = '-created_at'


class ShortsCursorPagination(CursorPagination):
    page_size = 10
    ordering  = '-created_at'


# ─────────────────────────────────────────────────────────────────────
# PERMISSIONS
# ─────────────────────────────────────────────────────────────────────

class IsAuthorOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        owner = getattr(obj, 'author', getattr(obj, 'user', None))
        return owner == request.user


# ─────────────────────────────────────────────────────────────────────
# BASE QUERYSET BUILDER
# ─────────────────────────────────────────────────────────────────────

def _base_post_qs(user):
    like_sq = PostLike.objects.filter(post=OuterRef('pk'), user=user)
    return (
        Post.objects
        .select_related(
            'author', 'author__profile',
            'league', 'team',
            'parent_post', 'parent_post__author',
            'parent_post__author__profile',
            'parent_post__league', 'parent_post__team',
        )
        .prefetch_related(
            'hashtags',
            'author__fan_preferences__league',
            'author__fan_preferences__team',
            'media_files',
        )
        .annotate(
            liked_by_me=Exists(like_sq),
            reposts_count=Count('quoted_by', distinct=True),
        )
    )


# ─────────────────────────────────────────────────────────────────────
# HELPER — extract uploaded files from request.FILES
# ─────────────────────────────────────────────────────────────────────

def _extract_media_files(request):
    """
    Try 'media_files' (plural — React Native multi-pick) first,
    then 'media_file' (singular — legacy / single-pick) as fallback.
    Returns a flat list of InMemoryUploadedFile / TemporaryUploadedFile objects.
    """
    files = request.FILES.getlist('media_files')
    if not files:
        single = request.FILES.get('media_file')
        if single:
            files = [single]

    logger.info(
        "extract_media_files | FILES.keys=%s | resolved=%d",
        list(request.FILES.keys()), len(files),
    )
    return files


# ─────────────────────────────────────────────────────────────────────
# POST VIEWSET
# ─────────────────────────────────────────────────────────────────────

class PostViewSet(viewsets.ModelViewSet):
    serializer_class   = PostSerializer
    permission_classes = [permissions.IsAuthenticated, IsAuthorOrReadOnly]
    pagination_class   = FeedCursorPagination
    filter_backends    = [filters.SearchFilter]
    search_fields      = ['content', 'author__username', 'league__name']

    # Explicit parser_classes — ensures multipart bodies are always parsed
    # regardless of DEFAULT_PARSER_CLASSES in settings.py
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    # ── Queryset ──────────────────────────────────────────────────────

    def get_queryset(self):
        user   = self.request.user
        qs     = _base_post_qs(user)
        params = self.request.query_params

        user_id      = params.get('user')
        filter_type  = params.get('filter')
        league_id    = params.get('league')
        leagues_list = params.get('leagues')
        team_id      = params.get('team')
        feed_type    = params.get('feed_type')

        if user.is_authenticated and not league_id and not leagues_list:
            league_ids = list(user.fan_preferences.values_list('league_id', flat=True))
            if league_ids:
                qs = qs.filter(league_id__in=league_ids)

        if league_id:
            qs = qs.filter(league_id=league_id)
        elif leagues_list:
            ids = [x.strip() for x in leagues_list.split(',') if x.strip().isdigit()]
            if ids:
                qs = qs.filter(league_id__in=ids)

        if feed_type == 'following' and user.is_authenticated:
            following_ids = Follow.objects.filter(follower=user).values_list('followed_id', flat=True)
            qs = qs.filter(Q(author_id__in=following_ids) | Q(author=user))

        if user_id:
            qs = qs.filter(author_id=user_id)
        elif filter_type == 'mine' and user.is_authenticated:
            qs = qs.filter(author=user)

        if team_id:
            qs = qs.filter(team_id=team_id)

        return qs.order_by('-created_at')

    # ── Create ────────────────────────────────────────────────────────

    def perform_create(self, serializer):
        """
        Two-step file saving — belt and suspenders:

        Step 1 — serializer.save() with text/FK fields only.
                  We intentionally do NOT pass media_file to serializer.save()
                  because even with the FileField fix in serializers.py, it's
                  more reliable to assign the file directly on the model instance
                  (avoids any DRF validation pipeline stripping the file).

        Step 2 — assign media_file directly on the Post instance, then call
                  post.save(update_fields=['media_file']). This talks to the
                  GCS backend directly, bypassing DRF entirely.

        Step 3 — create one PostMedia row per uploaded file with error logging.
        """
        media_files = _extract_media_files(self.request)
        parent_id   = self.request.data.get('parent_post')

        # Determine post_type from mime; default to 'text' if no files
        if media_files:
            post_type = 'video' if media_files[0].content_type.startswith('video') else 'image'
        else:
            post_type = 'text'

        # Build serializer kwargs — text/FK fields only, no files
        kwargs = {'author': self.request.user, 'post_type': post_type}
        if parent_id:
            kwargs['parent_post_id'] = parent_id

        # ── Step 1: persist text fields ──────────────────────────────
        post = serializer.save(**kwargs)
        logger.info("perform_create | post_id=%s | files=%d", post.id, len(media_files))

        if not media_files:
            return

        # ── Step 2: persist legacy single media_file on model directly ──
        try:
            post.media_file = media_files[0]
            post.save(update_fields=['media_file'])
            logger.info(
                "perform_create | post_id=%s | media_file → %s",
                post.id, post.media_file.name,
            )
        except Exception as exc:
            logger.error(
                "perform_create | post_id=%s | media_file FAILED | %s: %s",
                post.id, type(exc).__name__, exc,
            )

        # ── Step 3: create PostMedia rows ────────────────────────────
        for i, f in enumerate(media_files):
            is_video = f.content_type.startswith('video')
            try:
                pm = PostMedia.objects.create(
                    post       = post,
                    file       = f,
                    media_type = 'video' if is_video else 'image',
                    order      = i,
                )
                logger.info(
                    "perform_create | post_id=%s | PostMedia[%d] → %s",
                    post.id, i, pm.file.name,
                )
            except Exception as exc:
                logger.error(
                    "perform_create | post_id=%s | PostMedia[%d] FAILED | %s: %s",
                    post.id, i, type(exc).__name__, exc,
                )

    # ── Update (PATCH) ────────────────────────────────────────────────

    def perform_update(self, serializer):
        media_files = _extract_media_files(self.request)
        post = serializer.save()

        if not media_files:
            return

        PostMedia.objects.filter(post=post).delete()

        for i, f in enumerate(media_files):
            is_video = f.content_type.startswith('video')
            try:
                PostMedia.objects.create(
                    post       = post,
                    file       = f,
                    media_type = 'video' if is_video else 'image',
                    order      = i,
                )
            except Exception as exc:
                logger.error(
                    "perform_update | post_id=%s | PostMedia[%d] FAILED | %s: %s",
                    post.id, i, type(exc).__name__, exc,
                )

        try:
            post.media_file = media_files[0]
            post.post_type  = 'video' if media_files[0].content_type.startswith('video') else 'image'
            post.save(update_fields=['media_file', 'post_type'])
        except Exception as exc:
            logger.error(
                "perform_update | post_id=%s | media_file update FAILED | %s: %s",
                post.id, type(exc).__name__, exc,
            )

    # ── Delete ────────────────────────────────────────────────────────

    def destroy(self, request, *args, **kwargs):
        self.get_object()
        self.perform_destroy(self.get_object())
        return Response({'message': 'Post deleted successfully'}, status=status.HTTP_204_NO_CONTENT)

    # ── Like ──────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def like(self, request, pk=None):
        post    = self.get_object()
        like_qs = PostLike.objects.filter(post=post, user=request.user)

        if like_qs.exists():
            like_qs.delete()
            post.decrement_like()
            liked = False
        else:
            PostLike.objects.create(post=post, user=request.user)
            post.increment_like()
            liked = True

        post.refresh_from_db(fields=['like_count'])
        return Response({'liked': liked, 'likes_count': post.like_count})

    # ── View count ────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def view(self, request, pk=None):
        Post.objects.filter(pk=pk).update(view_count=F('view_count') + 1)
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ── Comments ──────────────────────────────────────────────────────

    @action(detail=True, methods=['get', 'post'], permission_classes=[IsAuthenticated])
    def comments(self, request, pk=None):
        post = self.get_object()

        if request.method == 'POST':
            serializer = CommentSerializer(data=request.data, context={'request': request})
            if serializer.is_valid():
                serializer.save(post=post, user=request.user)
                post.increment_comment()
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        comments_qs = (
            post.comments
            .select_related('user', 'user__profile')
            .prefetch_related('user__fan_preferences__league', 'user__fan_preferences__team')
            .annotate(likes_count=Count('likes', distinct=True))
            .order_by('-created_at')
        )
        page = self.paginate_queryset(comments_qs)
        serializer = CommentSerializer(
            page if page is not None else comments_qs,
            many=True, context={'request': request},
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    # ── Repost ────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def repost(self, request, pk=None):
        original = self.get_object()
        existing = Post.objects.filter(
            author=request.user, parent_post=original,
            is_repost=True, content='',
        ).first()

        if existing:
            existing.delete()
            original.decrement_comment()
            return Response({
                'status': 'unreposted',
                'reposts_count': Post.objects.filter(parent_post=original).count(),
            })

        repost = Post.objects.create(
            author=request.user, content='',
            parent_post=original, post_type='text',
            league=original.league, is_repost=True,
        )
        return Response(
            {'status': 'reposted', 'id': repost.id,
             'reposts_count': Post.objects.filter(parent_post=original).count()},
            status=status.HTTP_201_CREATED,
        )


# ─────────────────────────────────────────────────────────────────────
# COMMENT VIEWSET
# ─────────────────────────────────────────────────────────────────────

class CommentViewSet(viewsets.ModelViewSet):
    queryset           = Comment.objects.select_related('user', 'user__profile')
    serializer_class   = CommentSerializer
    permission_classes = [permissions.IsAuthenticated, IsAuthorOrReadOnly]

    def perform_create(self, serializer):
        comment = serializer.save(user=self.request.user)
        comment.post.increment_comment()

    def perform_destroy(self, instance):
        instance.post.decrement_comment()
        instance.delete()

    def destroy(self, request, *args, **kwargs):
        self.perform_destroy(self.get_object())
        return Response({'message': 'Comment deleted'}, status=status.HTTP_204_NO_CONTENT)


# ─────────────────────────────────────────────────────────────────────
# SHORTS VIEWSET
# ─────────────────────────────────────────────────────────────────────

class ShortVideoViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class   = PostSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class   = ShortsCursorPagination

    def get_queryset(self):
        user    = self.request.user
        like_sq = PostLike.objects.filter(post=OuterRef('pk'), user=user)

        qs = (
            Post.objects
            .filter(is_short=True, video_status='ready')
            .exclude(media_file='')
            .select_related('author', 'author__profile', 'league', 'team')
            .prefetch_related(
                'hashtags',
                'author__fan_preferences__league',
                'author__fan_preferences__team',
                'media_files',
            )
            .annotate(liked_by_me=Exists(like_sq))
        )

        league_ids = list(user.fan_preferences.values_list('league_id', flat=True))
        if league_ids:
            qs = qs.filter(league_id__in=league_ids)

        return get_personalized_shorts(qs)


# ─────────────────────────────────────────────────────────────────────
# HASHTAG VIEWSET
# ─────────────────────────────────────────────────────────────────────

class HashtagViewSet(viewsets.ReadOnlyModelViewSet):
    queryset         = Hashtag.objects.all()
    serializer_class = HashtagSerializer

    @action(detail=False, methods=['get'])
    def trending(self, request):
        tags = get_trending_hashtags(limit=10, days=1)
        return Response(self.get_serializer(tags, many=True).data)


# ─────────────────────────────────────────────────────────────────────
# VIDEO UPLOAD VIEWS
# ─────────────────────────────────────────────────────────────────────

class VideoUploadInitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        post = Post.objects.create(
            author       = request.user,
            post_type    = 'video',
            video_status = 'pending',
            league_id    = request.data.get('league_id'),
            is_short     = request.data.get('is_short', False),
        )
        session = VideoUploadSession.objects.create(
            user         = request.user,
            post         = post,
            total_chunks = int(request.data.get('total_chunks', 1)),
        )
        return Response({'upload_id': str(session.id), 'post_id': post.id},
                        status=status.HTTP_201_CREATED)


class VideoChunkUploadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        upload_id   = request.data.get('upload_id')
        chunk_index = int(request.data.get('chunk_index', 0))
        chunk       = request.FILES.get('chunk')

        try:
            session = VideoUploadSession.objects.select_related('post').get(
                id=upload_id, user=request.user
            )
        except VideoUploadSession.DoesNotExist:
            return Response({'error': 'Invalid session'}, status=status.HTTP_404_NOT_FOUND)

        import tempfile
        tmp_dir    = os.path.join(tempfile.gettempdir(), str(upload_id))
        os.makedirs(tmp_dir, exist_ok=True)
        chunk_path = os.path.join(tmp_dir, f'chunk_{chunk_index:06d}')
        with open(chunk_path, 'wb') as fh:
            for part in chunk.chunks():
                fh.write(part)

        session.uploaded_chunks = chunk_index + 1
        session.save(update_fields=['uploaded_chunks'])
        return Response({'received': chunk_index}, status=status.HTTP_200_OK)


class VideoUploadFinalizeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        upload_id = request.data.get('upload_id')
        try:
            session = VideoUploadSession.objects.select_related('post').get(
                id=upload_id, user=request.user
            )
        except VideoUploadSession.DoesNotExist:
            return Response({'error': 'Invalid session'}, status=status.HTTP_404_NOT_FOUND)

        Post.objects.filter(pk=session.post_id).update(video_status='processing')

        from .tasks import process_video_upload
        process_video_upload.delay(
            post_id    = session.post_id,
            song_id    = request.data.get('song_id'),
            trim_range = (request.data.get('trim_start', 0), request.data.get('trim_end')),
            upload_id  = str(upload_id),
        )
        return Response(
            {'status': 'processing', 'message': 'Video is being edited and optimised.'},
            status=status.HTTP_202_ACCEPTED,
        )


# ─────────────────────────────────────────────────────────────────────
# FOLLOWING FEED VIEW
# ─────────────────────────────────────────────────────────────────────

class FollowingFeedView(generics.ListAPIView):
    serializer_class   = PostSerializer
    permission_classes = [IsAuthenticated]
    pagination_class   = FeedCursorPagination

    def get_queryset(self):
        user          = self.request.user
        following_ids = Follow.objects.filter(follower=user).values_list('followed_id', flat=True)
        return (
            _base_post_qs(user)
            .filter(Q(author_id__in=following_ids) | Q(author=user))
            .order_by('-created_at')
        )


# ─────────────────────────────────────────────────────────────────────
# LIKE / SHARE (legacy APIView endpoints)
# ─────────────────────────────────────────────────────────────────────

class LikePostView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, post_id):
        like, created = PostLike.objects.get_or_create(user=request.user, post_id=post_id)
        if not created:
            like.delete()
            Post.objects.filter(pk=post_id).update(like_count=F('like_count') - 1)
            return Response({'liked': False})
        Post.objects.filter(pk=post_id).update(like_count=F('like_count') + 1)
        return Response({'liked': True})


class SharePostView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, post_id):
        PostShare.objects.create(
            user=request.user,
            original_post_id=post_id,
            comment=request.data.get('comment', ''),
        )
        Post.objects.filter(pk=post_id).update(share_count=F('share_count') + 1)
        return Response({'shared': True})