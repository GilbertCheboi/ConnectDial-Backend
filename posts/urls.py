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
    VideoUploadInitView,
    VideoChunkUploadView,
    VideoUploadFinalizeView,
)

router = DefaultRouter()

# Specific viewsets registered before the catch-all
router.register(r'shorts',   ShortVideoViewSet, basename='short')
router.register(r'comments', CommentViewSet,    basename='comment')
router.register(r'hashtags', HashtagViewSet,    basename='hashtag')
router.register(r'',         PostViewSet,        basename='post')

urlpatterns = [
    # ── ViewSet routes ───────────────────────────────────────────────
    path('', include(router.urls)),

    # ── Following feed ───────────────────────────────────────────────
    path('feed/following/', FollowingFeedView.as_view(), name='following-feed'),

    # ── Legacy like / share (kept for backward compatibility) ────────
    path('<int:post_id>/like/',  LikePostView.as_view(),  name='post-like'),
    path('<int:post_id>/share/', SharePostView.as_view(), name='post-share'),

    # ── Chunked video upload ─────────────────────────────────────────
    path('upload/init/',     VideoUploadInitView.as_view(),     name='video-upload-init'),
    path('upload/chunk/',    VideoChunkUploadView.as_view(),    name='video-upload-chunk'),
    path('upload/finalize/', VideoUploadFinalizeView.as_view(), name='video-upload-finalize'),
]
