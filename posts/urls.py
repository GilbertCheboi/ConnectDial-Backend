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

router.register(
    r'comments',
    CommentViewSet,
    basename='comment',
)

router.register(
    r'hashtags',
    HashtagViewSet,
    basename='hashtag',
)

# Main posts endpoint
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
    path(
        'share/<str:post_type>/<str:post_id>/',
        ShareRedirectView.as_view(),
        name='share-redirect',
    ),
]
