"""
views.py – ConnectDial Posts App
──────────────────────────────────────────────────────────────────────
FIXED LEAGUE FEED LOGIC
──────────────────────────────────────────────────────────────────────

FINAL FEED BEHAVIOUR:

1. feed_type=league&league_id=1
   → ONLY posts from EPL

2. feed_type=global
   → posts from ALL leagues selected by the user

3. feed_type=following
   → handled by FollowingFeedView separately

This version preserves:
✓ media upload fixes
✓ GCS saving
✓ shorts
✓ reposts
✓ comments
✓ pagination
✓ likes
✓ personalized global feed
✓ strict selected-league filtering
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

from .models import (
    Comment,
    Hashtag,
    Post,
    PostLike,
    PostMedia,
    PostShare,
    VideoUploadSession,
)

from .serializers import (
    CommentSerializer,
    HashtagSerializer,
    PostSerializer,
    VideoUploadSessionSerializer,
)

from .services import (
    get_personalized_shorts,
    get_trending_hashtags,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# PAGINATION
# ─────────────────────────────────────────────────────────────────────

class FeedCursorPagination(CursorPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 50
    ordering = '-created_at'


class ShortsCursorPagination(CursorPagination):
    page_size = 10
    ordering = '-created_at'


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
# BASE QUERYSET
# ─────────────────────────────────────────────────────────────────────

def _base_post_qs(user):
    like_sq = PostLike.objects.filter(
        post=OuterRef('pk'),
        user=user,
    )

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
            'media_files',
        )
        .annotate(
            liked_by_me=Exists(like_sq),
            reposts_count=Count('quoted_by', distinct=True),
        )
    )


# ─────────────────────────────────────────────────────────────────────
# MEDIA EXTRACTION HELPER
# ─────────────────────────────────────────────────────────────────────

def _extract_media_files(request):
    files = request.FILES.getlist('media_files')

    if not files:
        single = request.FILES.get('media_file')

        if single:
            files = [single]

    logger.info(
        "extract_media_files | keys=%s | resolved=%d",
        list(request.FILES.keys()),
        len(files),
    )

    return files


# ─────────────────────────────────────────────────────────────────────
# POST VIEWSET
# ─────────────────────────────────────────────────────────────────────

class PostViewSet(viewsets.ModelViewSet):
    serializer_class = PostSerializer

    permission_classes = [
        permissions.IsAuthenticated,
        IsAuthorOrReadOnly,
    ]

    pagination_class = FeedCursorPagination

    filter_backends = [filters.SearchFilter]

    search_fields = [
        'content',
        'author__username',
        'league__name',
    ]

    parser_classes = [
        MultiPartParser,
        FormParser,
        JSONParser,
    ]

    # ─────────────────────────────────────────────────────────────
    # QUERYSET
    # ─────────────────────────────────────────────────────────────

    def get_queryset(self):
        user = self.request.user

        qs = _base_post_qs(user)

        params = self.request.query_params

        user_id = params.get('user')
        filter_type = params.get('filter')

        # IMPORTANT FIX
        league_id = (
            params.get('league_id')
            or params.get('league')
        )

        leagues_list = params.get('leagues')
        team_id = params.get('team')
        feed_type = params.get('feed_type')

        # ─────────────────────────────────────────────────────
        # USER POSTS
        # ─────────────────────────────────────────────────────

        if user_id:
            qs = qs.filter(author_id=user_id)

        # ─────────────────────────────────────────────────────
        # TEAM FILTER
        # ─────────────────────────────────────────────────────

        if team_id:
            qs = qs.filter(team_id=team_id)

        # ─────────────────────────────────────────────────────
        # STRICT LEAGUE FEED
        #
        # Example:
        # ?feed_type=league&league_id=1
        #
        # RETURNS:
        # ONLY EPL POSTS
        # ─────────────────────────────────────────────────────

        if feed_type == 'league':

            if league_id:
                qs = qs.filter(league_id=league_id)

                logger.info(
                    "STRICT LEAGUE FEED | league_id=%s",
                    league_id,
                )

            else:
                qs = qs.none()

            return qs.order_by('-created_at')

        # ─────────────────────────────────────────────────────
        # GLOBAL FEED
        #
        # Returns posts from ALL leagues
        # selected by the user
        # ─────────────────────────────────────────────────────

        if feed_type == 'global':

            if user.is_authenticated:

                league_ids = list(
                    user.fan_preferences.values_list(
                        'league_id',
                        flat=True,
                    )
                )

                if league_ids:
                    qs = qs.filter(
                        league_id__in=league_ids
                    )

                    logger.info(
                        "GLOBAL FEED | user=%s | leagues=%s",
                        user.id,
                        league_ids,
                    )

            return qs.order_by('-created_at')

        # ─────────────────────────────────────────────────────
        # LEGACY leagues param
        # Example:
        # ?leagues=1,2,3
        # ─────────────────────────────────────────────────────

        if leagues_list:
            try:
                ids = [
                    int(x)
                    for x in leagues_list.split(',')
                    if x.strip()
                ]

                qs = qs.filter(league_id__in=ids)

            except Exception:
                pass

        return qs.order_by('-created_at')

    # ─────────────────────────────────────────────────────────────
    # CREATE
    # ─────────────────────────────────────────────────────────────

    def perform_create(self, serializer):
        media_files = _extract_media_files(self.request)

        parent_id = self.request.data.get('parent_post')

        if media_files:
            post_type = (
                'video'
                if media_files[0].content_type.startswith('video')
                else 'image'
            )
        else:
            post_type = 'text'

        kwargs = {
            'author': self.request.user,
            'post_type': post_type,
        }

        if parent_id:
            kwargs['parent_post_id'] = parent_id

        post = serializer.save(**kwargs)

        logger.info(
            "perform_create | post_id=%s | files=%d",
            post.id,
            len(media_files),
        )

        if not media_files:
            return

        # Save legacy media_file
        try:
            post.media_file = media_files[0]

            post.save(update_fields=['media_file'])

            logger.info(
                "perform_create | media saved | post=%s",
                post.id,
            )

        except Exception as exc:
            logger.error(
                "media_file save FAILED | %s: %s",
                type(exc).__name__,
                exc,
            )

        # Create PostMedia rows
        for i, f in enumerate(media_files):

            is_video = f.content_type.startswith('video')

            try:
                PostMedia.objects.create(
                    post=post,
                    file=f,
                    media_type='video' if is_video else 'image',
                    order=i,
                )

            except Exception as exc:
                logger.error(
                    "PostMedia FAILED | %s: %s",
                    type(exc).__name__,
                    exc,
                )

    # ─────────────────────────────────────────────────────────────
    # UPDATE
    # ─────────────────────────────────────────────────────────────

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
                    post=post,
                    file=f,
                    media_type='video' if is_video else 'image',
                    order=i,
                )

            except Exception as exc:
                logger.error(
                    "perform_update FAILED | %s: %s",
                    type(exc).__name__,
                    exc,
                )

        try:
            post.media_file = media_files[0]

            post.post_type = (
                'video'
                if media_files[0].content_type.startswith('video')
                else 'image'
            )

            post.save(
                update_fields=[
                    'media_file',
                    'post_type',
                ]
            )

        except Exception as exc:
            logger.error(
                "media update FAILED | %s: %s",
                type(exc).__name__,
                exc,
            )

    # ─────────────────────────────────────────────────────────────
    # DELETE
    # ─────────────────────────────────────────────────────────────

    def destroy(self, request, *args, **kwargs):
        post = self.get_object()

        self.perform_destroy(post)

        return Response(
            {'message': 'Post deleted successfully'},
            status=status.HTTP_204_NO_CONTENT,
        )

    # ─────────────────────────────────────────────────────────────
    # LIKE
    # ─────────────────────────────────────────────────────────────

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[IsAuthenticated],
    )
    def like(self, request, pk=None):

        post = self.get_object()

        like_qs = PostLike.objects.filter(
            post=post,
            user=request.user,
        )

        if like_qs.exists():

            like_qs.delete()

            post.decrement_like()

            liked = False

        else:

            PostLike.objects.create(
                post=post,
                user=request.user,
            )

            post.increment_like()

            liked = True

        post.refresh_from_db(fields=['like_count'])

        return Response({
            'liked': liked,
            'likes_count': post.like_count,
        })

    # ─────────────────────────────────────────────────────────────
    # VIEW COUNT
    # ─────────────────────────────────────────────────────────────

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[IsAuthenticated],
    )
    def view(self, request, pk=None):
        Post.objects.filter(pk=pk).update(
            view_count=F('view_count') + 1
        )

        return Response(
            status=status.HTTP_204_NO_CONTENT
        )

    # ─────────────────────────────────────────────────────────────
    # COMMENTS
    # ─────────────────────────────────────────────────────────────

    @action(
        detail=True,
        methods=['get', 'post'],
        permission_classes=[IsAuthenticated],
    )
    def comments(self, request, pk=None):

        post = self.get_object()

        if request.method == 'POST':
            serializer = CommentSerializer(
                data=request.data,
                context={'request': request},
            )

            if serializer.is_valid():
                serializer.save(
                    post=post,
                    user=request.user,
                )
                post.increment_comment()
                return Response(
                    serializer.data,
                    status=status.HTTP_201_CREATED,
                )

            # Improved logging
            logger.error(
                "Comment validation failed | post_id=%s | errors=%s | received_data=%s",
                pk, serializer.errors, request.data
            )

            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)        

        comments_qs = (
            post.comments
            .select_related(
                'user',
                'user__profile',
            )
            .prefetch_related(
                'user__fan_preferences__league',
                'user__fan_preferences__team',
            )
            .annotate(
                likes_count=Count('likes', distinct=True)
            )
            .order_by('-created_at')
        )

        page = self.paginate_queryset(comments_qs)

        serializer = CommentSerializer(
            page if page is not None else comments_qs,
            many=True,
            context={'request': request},
        )

        if page is not None:
            return self.get_paginated_response(
                serializer.data
            )

        return Response(serializer.data)

    # ─────────────────────────────────────────────────────────────
    # REPOST
    # ─────────────────────────────────────────────────────────────

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[IsAuthenticated],
    )
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

            original.decrement_comment()

            return Response({
                'status': 'unreposted',
                'reposts_count': Post.objects.filter(
                    parent_post=original
                ).count(),
            })

        repost = Post.objects.create(
            author=request.user,
            content='',
            parent_post=original,
            post_type='text',
            league=original.league,
            is_repost=True,
        )

        return Response(
            {
                'status': 'reposted',
                'id': repost.id,
                'reposts_count': Post.objects.filter(
                    parent_post=original
                ).count(),
            },
            status=status.HTTP_201_CREATED,
        )


# ─────────────────────────────────────────────────────────────────────
# COMMENTS
# ─────────────────────────────────────────────────────────────────────

class CommentViewSet(viewsets.ModelViewSet):
    queryset = Comment.objects.select_related(
        'user',
        'user__profile',
    )

    serializer_class = CommentSerializer

    permission_classes = [
        permissions.IsAuthenticated,
        IsAuthorOrReadOnly,
    ]

    def perform_create(self, serializer):
        comment = serializer.save(user=self.request.user)

        comment.post.increment_comment()

    def perform_destroy(self, instance):
        instance.post.decrement_comment()

        instance.delete()

    def destroy(self, request, *args, **kwargs):
        self.perform_destroy(self.get_object())

        return Response(
            {'message': 'Comment deleted'},
            status=status.HTTP_204_NO_CONTENT,
        )


# ─────────────────────────────────────────────────────────────────────
# SHORTS
# ─────────────────────────────────────────────────────────────────────

class ShortVideoViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PostSerializer

    permission_classes = [permissions.IsAuthenticated]

    pagination_class = ShortsCursorPagination

    def get_queryset(self):

        user = self.request.user

        like_sq = PostLike.objects.filter(
            post=OuterRef('pk'),
            user=user,
        )

        qs = (
            Post.objects
            .filter(
                is_short=True,
                video_status='ready',
            )
            .exclude(media_file='')
            .select_related(
                'author',
                'author__profile',
                'league',
                'team',
            )
            .prefetch_related(
                'hashtags',
                'author__fan_preferences__league',
                'author__fan_preferences__team',
                'media_files',
            )
            .annotate(
                liked_by_me=Exists(like_sq)
            )
        )

        league_ids = list(
            user.fan_preferences.values_list(
                'league_id',
                flat=True,
            )
        )

        if league_ids:
            qs = qs.filter(
                league_id__in=league_ids
            )

        return get_personalized_shorts(qs)


# ─────────────────────────────────────────────────────────────────────
# HASHTAGS
# ─────────────────────────────────────────────────────────────────────

class HashtagViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Hashtag.objects.all()

    serializer_class = HashtagSerializer

    @action(detail=False, methods=['get'])
    def trending(self, request):
        tags = get_trending_hashtags(
            limit=10,
            days=1,
        )

        return Response(
            self.get_serializer(tags, many=True).data
        )


# ─────────────────────────────────────────────────────────────────────
# FOLLOWING FEED
# ─────────────────────────────────────────────────────────────────────

class FollowingFeedView(generics.ListAPIView):
    serializer_class = PostSerializer

    permission_classes = [IsAuthenticated]

    pagination_class = FeedCursorPagination

    def get_queryset(self):

        user = self.request.user

        following_ids = Follow.objects.filter(
            follower=user
        ).values_list(
            'followed_id',
            flat=True,
        )

        return (
            _base_post_qs(user)
            .filter(
                Q(author_id__in=following_ids)
                | Q(author=user)
            )
            .order_by('-created_at')
        )
        
        
class VideoUploadInitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = VideoUploadSessionSerializer(data=request.data)  # optional

        league_id = request.data.get('league_id')

        post = Post.objects.create(
            author=request.user,
            post_type='video',
            video_status='pending',
            league_id=league_id,
            is_short=request.data.get('is_short', False),
            content=request.data.get('caption', ''),
        )

        session = VideoUploadSession.objects.create(
            user=request.user,
            post=post,
            total_chunks=int(request.data.get('total_chunks', 1)),
            file_name=request.data.get('file_name', ''),
        )

        return Response({
            'upload_id': str(session.id),
            'post_id': post.id,
            'status': 'initialized'
        }, status=status.HTTP_201_CREATED)        
        

# ─────────────────────────────────────────────────────────────────────
# LEGACY LIKE API
# ─────────────────────────────────────────────────────────────────────

class LikePostView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, post_id):

        like, created = PostLike.objects.get_or_create(
            user=request.user,
            post_id=post_id,
        )

        if not created:

            like.delete()

            Post.objects.filter(pk=post_id).update(
                like_count=F('like_count') - 1
            )

            return Response({'liked': False})

        Post.objects.filter(pk=post_id).update(
            like_count=F('like_count') + 1
        )

        return Response({'liked': True})


# ─────────────────────────────────────────────────────────────────────
# LEGACY SHARE API
# ─────────────────────────────────────────────────────────────────────

class SharePostView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, post_id):

        PostShare.objects.create(
            user=request.user,
            original_post_id=post_id,
            comment=request.data.get('comment', ''),
        )

        Post.objects.filter(pk=post_id).update(
            share_count=F('share_count') + 1
        )

        return Response({'shared': True})
# ─────────────────────────────────────────────────────────────────────
# VIDEO CHUNK UPLOAD
# ─────────────────────────────────────────────────────────────────────

class VideoChunkUploadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):

        upload_id = request.data.get('upload_id')

        chunk_index = int(
            request.data.get('chunk_index', 0)
        )

        chunk = request.FILES.get('chunk')

        try:

            session = (
                VideoUploadSession.objects
                .select_related('post')
                .get(
                    id=upload_id,
                    user=request.user,
                )
            )

        except VideoUploadSession.DoesNotExist:

            return Response(
                {'error': 'Invalid session'},
                status=status.HTTP_404_NOT_FOUND,
            )

        import tempfile

        tmp_dir = os.path.join(
            tempfile.gettempdir(),
            str(upload_id),
        )

        os.makedirs(tmp_dir, exist_ok=True)

        chunk_path = os.path.join(
            tmp_dir,
            f'chunk_{chunk_index:06d}',
        )

        with open(chunk_path, 'wb') as fh:

            for part in chunk.chunks():
                fh.write(part)

        session.uploaded_chunks = chunk_index + 1

        session.save(update_fields=['uploaded_chunks'])

        return Response(
            {'received': chunk_index},
            status=status.HTTP_200_OK,
        )


# ─────────────────────────────────────────────────────────────────────
# VIDEO FINALIZE
# ─────────────────────────────────────────────────────────────────────

class VideoUploadFinalizeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):

        upload_id = request.data.get('upload_id')

        try:

            session = (
                VideoUploadSession.objects
                .select_related('post')
                .get(
                    id=upload_id,
                    user=request.user,
                )
            )

        except VideoUploadSession.DoesNotExist:

            return Response(
                {'error': 'Invalid session'},
                status=status.HTTP_404_NOT_FOUND,
            )

        Post.objects.filter(
            pk=session.post_id
        ).update(
            video_status='processing'
        )

        from .tasks import process_video_upload

        process_video_upload.delay(
            post_id=session.post_id,
            song_id=request.data.get('song_id'),
            trim_range=(
                request.data.get('trim_start', 0),
                request.data.get('trim_end'),
            ),
            upload_id=str(upload_id),
        )

        return Response(
            {
                'status': 'processing',
                'message': 'Video is being edited and optimised.',
            },
            status=status.HTTP_202_ACCEPTED,
        )