from django.urls import path
from . import views

urlpatterns = [
    # ── Feed ──────────────────────────────────────────────────────────────────
    path('shorts/feed/', views.ShortVideoFeedView.as_view(), name='short-video-feed'),

    # ── Streaming (Range-capable, supports up to 2-hr videos) ─────────────────
    path('shorts/<uuid:pk>/stream/', views.ShortVideoStreamView.as_view(), name='short-video-stream'),

    # ── Engagement ────────────────────────────────────────────────────────────
    path('shorts/<uuid:pk>/like/',    views.VideoLikeToggleView.as_view(),  name='short-video-like'),
    path('shorts/<uuid:pk>/view/',    views.VideoViewRecordView.as_view(),  name='short-video-view'),
    path('shorts/<uuid:pk>/share/',   views.VideoShareRecordView.as_view(), name='short-video-share'),
    # ✅ In-app reshare endpoint — used by the share sheet "Reshare" button
    path('shorts/<uuid:pk>/reshare/', views.VideoReshareView.as_view(),     name='short-video-reshare'),

    # ── Comments ──────────────────────────────────────────────────────────────
    path('shorts/<uuid:pk>/comments/', views.VideoCommentListCreateView.as_view(), name='short-video-comments'),
    path(
        'shorts/<uuid:pk>/comments/<uuid:comment_pk>/replies/',
        views.CommentRepliesListView.as_view(),
        name='short-video-comment-replies',
    ),

    # ── Individual Comment Management ─────────────────────────────────────────
    path('comments/<uuid:pk>/', views.CommentDetailView.as_view(), name='comment-detail'),
]