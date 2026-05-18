"""
urls.py – ConnectDial Posts App
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    PostViewSet,
    CommentViewSet,
    ShortVideoViewSet,
    HashtagViewSet,
    FollowingFeedView,
    LikePostView,
    SharePostView,
    ShareRedirectView,
    VideoUploadInitView,
    VideoChunkUploadView,
    VideoUploadFinalizeView,
)

router = DefaultRouter()

# ─────────────────────────────────────────────────────────────────────
# VIEWSETS
# ─────────────────────────────────────────────────────────────────────

router.register(
    r'shorts',
    ShortVideoViewSet,
    basename='short',
)

# Renamed prefix: 'comments' → 'post-comments' to avoid operationId
# collision with the nested comments action on PostViewSet
# (POST /posts/{id}/comments/ vs POST /posts/comments/).
router.register(
    r'post-comments',
    CommentViewSet,
    basename='comment',
)

router.register(
    r'hashtags',
    HashtagViewSet,
    basename='hashtag',
)

# Main posts endpoint — must be last so its empty prefix r''
# doesn't swallow the other registrations above.
router.register(
    r'',
    PostViewSet,
    basename='post',
)

# ─────────────────────────────────────────────────────────────────────
# URLPATTERNS
# ─────────────────────────────────────────────────────────────────────

urlpatterns = [

    # ── DRF ROUTER ENDPOINTS ──────────────────────────────────────
    path('', include(router.urls)),

    # ── FOLLOWING FEED ────────────────────────────────────────────
    path(
        'feed/following/',
        FollowingFeedView.as_view(),
        name='following-feed',
    ),

    # ── VIDEO UPLOAD API ──────────────────────────────────────────
    path(
        'upload/init/',
        VideoUploadInitView.as_view(),
        name='video-upload-init',
    ),

    path(
        'upload/chunk/',
        VideoChunkUploadView.as_view(),
        name='video-upload-chunk',
    ),

    path(
        'upload/finalize/',
        VideoUploadFinalizeView.as_view(),
        name='video-upload-finalize',
    ),

    # ── SHARE REDIRECT ────────────────────────────────────────────
    # Using <int:post_id> for numeric IDs; keep <str:post_type> for
    # the type slug (e.g. "post", "short").
    path(
        'share/<str:post_type>/<int:post_id>/',
        ShareRedirectView.as_view(),
        name='share-redirect',
    ),
]