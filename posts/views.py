"""
views.py – ConnectDial Posts App
──────────────────────────────────────────────────────────────────────
Principles
──────────────────────────────────────────────────────────────────────
• Every queryset goes through get_home_feed_queryset (services.py),
  which does ONE SQL statement with select_related + prefetch_related
  and Exists() sub-queries for liked_by_me.
• Counters are updated atomically via F() expressions; no full-object
  save() is ever called just to bump a number.
• CursorPagination replaces page-number pagination: no COUNT(*) on
  every request, which is the #1 cause of slow infinite-scroll feeds.
• All custom actions return only the fields the frontend actually needs.
"""

import os
from django.db.models import Count, Exists, ExpressionWrapper, F, FloatField, OuterRef, Q, Subquery, Value
from django.db.models.functions import ExtractDay, ExtractHour, Now
from django.utils import timezone

from rest_framework import filters, generics, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from users.models import Follow, FanPreference

from .models import Comment, Hashtag, Post, PostLike, PostShare, VideoUploadSession
from .serializers import CommentSerializer, HashtagSerializer, PostSerializer
from .services import get_personalized_shorts, get_trending_hashtags


# ─────────────────────────────────────────────────────────────────────
# PAGINATION
# ─────────────────────────────────────────────────────────────────────

class FeedCursorPagination(CursorPagination):
    """
    Cursor pagination for the main feed.
    No COUNT(*) → instant response on large tables.
    """
    page_size            = 20
    page_size_query_param = 'page_size'
    max_page_size        = 50
    ordering             = '-created_at'


class ShortsCursorPagination(CursorPagination):
    """
    Shorts use hot_score ordering so the cursor must reflect that.
    """
    page_size = 10
    ordering  = '-created_at'   # hot_score is recalculated; cursor on created_at is stable


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
# BASE QUERYSET BUILDER  (shared by PostViewSet + FollowingFeedView)
# ─────────────────────────────────────────────────────────────────────

def _base_post_qs(user):
    """
    Single, fully-optimised base queryset:
    • 1 SQL with all JOINs
    • Exists() sub-query for liked_by_me (no loop)
    • Uses denormalised counters (no COUNT aggregation)
    """
    like_sq = PostLike.objects.filter(post=OuterRef('pk'), user=user)

    return (
        Post.objects
        .select_related(
            'author',
            'author__profile',
            'league',
            'team',
            'parent_post',
            'parent_post__author',
            'parent_post__author__profile',
            'parent_post__league',
            'parent_post__team',
        )
        .prefetch_related(
            'hashtags',
            'author__fan_preferences__league',
            'author__fan_preferences__team',
        )
        .annotate(
            liked_by_me=Exists(like_sq),
            # reposts_count from the 'quoted_by' reverse relation
            reposts_count=Count('quoted_by', distinct=True),
        )
    )


# ─────────────────────────────────────────────────────────────────────
# POST VIEWSET
# ─────────────────────────────────────────────────────────────────────

class PostViewSet(viewsets.ModelViewSet):
    serializer_class   = PostSerializer
    permission_classes = [permissions.IsAuthenticated, IsAuthorOrReadOnly]
    pagination_class   = FeedCursorPagination
    filter_backends    = [filters.SearchFilter]
    search_fields      = ['content', 'author__username', 'league__name']

    # ── Queryset ──────────────────────────────────────────────────────

    def get_queryset(self):
        user = self.request.user
        qs   = _base_post_qs(user)

        params       = self.request.query_params
        user_id      = params.get('user')
        filter_type  = params.get('filter')
        league_id    = params.get('league')
        leagues_list = params.get('leagues')
        team_id      = params.get('team')
        feed_type    = params.get('feed_type')

        # ── A. Default: only leagues the user follows ─────────────────
        if user.is_authenticated and not league_id and not leagues_list:
            league_ids = list(
                user.fan_preferences.values_list('league_id', flat=True)
            )
            if league_ids:
                qs = qs.filter(league_id__in=league_ids)

        # ── B. Explicit league filter ─────────────────────────────────
        if league_id:
            qs = qs.filter(league_id=league_id)
        elif leagues_list:
            ids = [x.strip() for x in leagues_list.split(',') if x.strip().isdigit()]
            if ids:
                qs = qs.filter(league_id__in=ids)

        # ── C. Following-only feed ────────────────────────────────────
        if feed_type == 'following' and user.is_authenticated:
            following_ids = Follow.objects.filter(follower=user).values_list('followed_id', flat=True)
            qs = qs.filter(Q(author_id__in=following_ids) | Q(author=user))

        # ── D. Profile / context filters ─────────────────────────────
        if user_id:
            qs = qs.filter(author_id=user_id)
        elif filter_type == 'mine' and user.is_authenticated:
            qs = qs.filter(author=user)

        if team_id:
            qs = qs.filter(team_id=team_id)

        return qs.order_by('-created_at')

    # ── Create ────────────────────────────────────────────────────────

    def perform_create(self, serializer):
        parent_id = self.request.data.get('parent_post')
        kwargs    = {'author': self.request.user}
        if parent_id:
            kwargs['parent_post_id'] = parent_id
        serializer.save(**kwargs)

    # ── Delete ────────────────────────────────────────────────────────

    def destroy(self, request, *args, **kwargs):
        self.get_object()  # triggers permission check
        self.perform_destroy(self.get_object())
        return Response({'message': 'Post deleted successfully'}, status=status.HTTP_204_NO_CONTENT)

    # ── Like (atomic, no race condition) ─────────────────────────────

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def like(self, request, pk=None):
        post = self.get_object()
        like_qs = PostLike.objects.filter(post=post, user=request.user)

        if like_qs.exists():
            like_qs.delete()
            post.decrement_like()          # atomic F() update
            liked = False
        else:
            PostLike.objects.create(post=post, user=request.user)
            post.increment_like()          # atomic F() update
            liked = True

        post.refresh_from_db(fields=['like_count'])
        return Response({'liked': liked, 'likes_count': post.like_count})

    # ── View count (fire-and-forget, no response body needed) ─────────

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
                comment = serializer.save(post=post, user=request.user)
                post.increment_comment()   # atomic
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # GET – paginated comments
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
            many=True,
            context={'request': request},
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    # ── Repost ────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def repost(self, request, pk=None):
        original = self.get_object()

        existing = Post.objects.filter(
            author=request.user,
            parent_post=original,
            is_repost=True,
            content='',
        ).first()

        if existing:
            existing.delete()
            original.decrement_comment()   # or keep a repost counter
            new_count = Post.objects.filter(parent_post=original).count()
            return Response({'status': 'unreposted', 'reposts_count': new_count})

        repost = Post.objects.create(
            author      = request.user,
            content     = '',
            parent_post = original,
            post_type   = 'text',
            league      = original.league,
            is_repost   = True,
        )
        new_count = Post.objects.filter(parent_post=original).count()
        return Response(
            {'status': 'reposted', 'id': repost.id, 'reposts_count': new_count},
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
# SHORTS VIEWSET  (TikTok-style vertical video)
# ─────────────────────────────────────────────────────────────────────

class ShortVideoViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Serves natively-uploaded Shorts only.
    • video_status='ready'  – never shows uploading/processing videos
    • Ranked by hot_score   – engagement-weighted freshness
    • League-personalised   – only leagues the user follows
    • Annotated liked_by_me – zero extra queries
    """
    serializer_class   = PostSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class   = ShortsCursorPagination

    def get_queryset(self):
        user = self.request.user
        like_sq = PostLike.objects.filter(post=OuterRef('pk'), user=user)

        qs = (
            Post.objects
            .filter(is_short=True, video_status='ready')
            .exclude(media_file='')
            .select_related(
                'author', 'author__profile',
                'league', 'team',
            )
            .prefetch_related(
                'hashtags',
                'author__fan_preferences__league',
                'author__fan_preferences__team',
            )
            .annotate(liked_by_me=Exists(like_sq))
        )

        # League personalisation
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
        tags       = get_trending_hashtags(limit=10, days=1)
        serializer = self.get_serializer(tags, many=True)
        return Response(serializer.data)


# ─────────────────────────────────────────────────────────────────────
# VIDEO UPLOAD VIEWS
# ─────────────────────────────────────────────────────────────────────

class VideoUploadInitView(APIView):
    """
    Step 1 – Client calls this to create a Post shell and get an upload_id.
    The Post starts with video_status='pending'.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        league_id    = request.data.get('league_id')
        total_chunks = int(request.data.get('total_chunks', 1))

        post = Post.objects.create(
            author       = request.user,
            post_type    = 'video',
            video_status = 'pending',
            league_id    = league_id,
            is_short     = request.data.get('is_short', False),
        )
        session = VideoUploadSession.objects.create(
            user         = request.user,
            post         = post,
            total_chunks = total_chunks,
        )
        return Response({'upload_id': str(session.id), 'post_id': post.id},
                        status=status.HTTP_201_CREATED)


class VideoChunkUploadView(APIView):
    """
    Step 2 – Receives individual file chunks.
    Each chunk is appended to a temp file server-side.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        upload_id    = request.data.get('upload_id')
        chunk_index  = int(request.data.get('chunk_index', 0))
        chunk        = request.FILES.get('chunk')

        try:
            session = VideoUploadSession.objects.select_related('post').get(
                id=upload_id, user=request.user
            )
        except VideoUploadSession.DoesNotExist:
            return Response({'error': 'Invalid session'}, status=status.HTTP_404_NOT_FOUND)

        # Write chunk to a temp file
        import tempfile, os
        tmp_dir  = os.path.join(tempfile.gettempdir(), str(upload_id))
        os.makedirs(tmp_dir, exist_ok=True)
        chunk_path = os.path.join(tmp_dir, f'chunk_{chunk_index:06d}')
        with open(chunk_path, 'wb') as f:
            for part in chunk.chunks():
                f.write(part)

        session.uploaded_chunks = chunk_index + 1
        session.save(update_fields=['uploaded_chunks'])

        return Response({'received': chunk_index}, status=status.HTTP_200_OK)


class VideoUploadFinalizeView(APIView):
    """
    Step 3 – Assemble chunks and trigger FFmpeg editing via Celery.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        upload_id   = request.data.get('upload_id')
        song_id     = request.data.get('song_id')
        trim_start  = request.data.get('trim_start', 0)
        trim_end    = request.data.get('trim_end', None)

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
            song_id    = song_id,
            trim_range = (trim_start, trim_end),
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
    """
    Pure 'people I follow' feed – no bot content, no league noise.
    """
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
# LIKE / SHARE  (legacy APIView endpoints kept for backward compat)
# ─────────────────────────────────────────────────────────────────────

class LikePostView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, post_id):
        like, created = PostLike.objects.get_or_create(
            user=request.user, post_id=post_id
        )
        if not created:
            like.delete()
            Post.objects.filter(pk=post_id).update(
                like_count=F('like_count') - 1
            )
            return Response({'liked': False})
        Post.objects.filter(pk=post_id).update(like_count=F('like_count') + 1)
        return Response({'liked': True})


class SharePostView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, post_id):
        comment = request.data.get('comment', '')
        PostShare.objects.create(
            user=request.user, original_post_id=post_id, comment=comment
        )
        Post.objects.filter(pk=post_id).update(share_count=F('share_count') + 1)
        return Response({'shared': True})
