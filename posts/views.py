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
✓ deep link share redirect (Play Store fallback)
"""

import os
import logging

from django.db.models import Count, Exists, F, OuterRef, Q
from django.http import HttpResponse
from django.views import View

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
# DEEP LINK CONSTANTS
# ─────────────────────────────────────────────────────────────────────

PLAY_STORE_URL = "https://play.google.com/store/apps/details?id=com.connectmobile.app&pcampaignid=web_share"
APP_SCHEME     = "connectdial"
APP_DOMAIN     = "https://api.connectdial.com"


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
# DEEP LINK SHARE REDIRECT
# ─────────────────────────────────────────────────────────────────────
# Handles public share links opened in a browser.
#
# Flow:
#   1. User shares: https://api.connectdial.com/share/post/123/
#   2. Browser opens that URL
#   3. Page immediately tries connectdial://share/post/123
#   4. If app installed → app opens to that post
#   5. If app NOT installed → after 2.5s → Play Store
#
# No authentication required — this is a public redirect page.
# ─────────────────────────────────────────────────────────────────────

class ShareRedirectView(View):
    """
    Public view — no DRF auth, plain Django View.
    Accessible at: /share/<post_type>/<post_id>/

    Valid post_type values: post, profile, event
    """

    VALID_TYPES = {"post", "profile", "event"}

    def get(self, request, post_type: str, post_id: str):

        if post_type not in self.VALID_TYPES:
            return HttpResponse("Invalid share type.", status=400)

        deep_link  = f"{APP_SCHEME}://share/{post_type}/{post_id}"
        canonical  = f"{APP_DOMAIN}/share/{post_type}/{post_id}/"
        type_label = post_type.capitalize()   # Post / Profile / Event

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Opening ConnectDial\u2026</title>

  <!-- Open Graph — controls WhatsApp / Twitter link preview card -->
  <meta property="og:title"       content="Check this {type_label} on ConnectDial" />
  <meta property="og:description" content="Open ConnectDial to view this {type_label}." />
  <meta property="og:image"       content="{APP_DOMAIN}/static/og-image.png" />
  <meta property="og:url"         content="{canonical}" />
  <meta property="og:type"        content="website" />

  <!-- Twitter card -->
  <meta name="twitter:card"        content="summary_large_image" />
  <meta name="twitter:title"       content="Check this {type_label} on ConnectDial" />
  <meta name="twitter:description" content="Open ConnectDial to view this {type_label}." />
  <meta name="twitter:image"       content="{APP_DOMAIN}/static/og-image.png" />

  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #0f0f0f;
      color: #ffffff;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 24px;
      text-align: center;
    }}
    .logo {{
      width: 80px;
      height: 80px;
      border-radius: 20px;
      background: #1a73e8;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 36px;
      margin-bottom: 24px;
    }}
    h1 {{ font-size: 22px; margin-bottom: 8px; }}
    p  {{ font-size: 14px; color: #aaaaaa; margin-bottom: 32px; }}
    .btn {{
      display: inline-block;
      padding: 14px 32px;
      border-radius: 50px;
      font-size: 16px;
      font-weight: 600;
      text-decoration: none;
      cursor: pointer;
      border: none;
    }}
    .btn-primary {{
      background: #1a73e8;
      color: #ffffff;
      margin-bottom: 12px;
      width: 100%;
      max-width: 320px;
    }}
    .btn-secondary {{
      background: transparent;
      color: #aaaaaa;
      border: 1px solid #333;
      width: 100%;
      max-width: 320px;
      font-size: 14px;
    }}
    .spinner {{
      width: 20px; height: 20px;
      border: 2px solid #ffffff44;
      border-top-color: #ffffff;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
      display: inline-block;
      margin-right: 8px;
      vertical-align: middle;
    }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
  </style>
</head>
<body>

  <div class="logo">\U0001f4f1</div>
  <h1>Opening ConnectDial\u2026</h1>
  <p>If the app doesn\u2019t open automatically,<br/>download it from the Play Store.</p>

  <a id="open-btn" href="{deep_link}" class="btn btn-primary">
    <span class="spinner"></span> Open in ConnectDial
  </a>

  <br/><br/>

  <a href="{PLAY_STORE_URL}" class="btn btn-secondary">
    Download ConnectDial
  </a>

  <script>
    // Immediately try to open the app via custom URI scheme
    window.location.href = "{deep_link}";

    // After 2.5s, if the app didn't open (not installed),
    // redirect to Play Store
    var fallbackTimer = setTimeout(function () {{
      window.location.href = "{PLAY_STORE_URL}";
    }}, 2500);

    // Manual tap on the button: reset the timer
    document.getElementById("open-btn").addEventListener("click", function () {{
      clearTimeout(fallbackTimer);
      setTimeout(function () {{
        window.location.href = "{PLAY_STORE_URL}";
      }}, 2500);
    }});

    // Page goes hidden = app opened successfully, cancel Play Store redirect
    document.addEventListener("visibilitychange", function () {{
      if (document.hidden) {{
        clearTimeout(fallbackTimer);
      }}
    }});
  </script>

</body>
</html>"""

        return HttpResponse(html, content_type="text/html; charset=utf-8")


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