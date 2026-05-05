from django.urls import path
from . import views

urlpatterns = [
    # --- Feed ---
    path('shorts/feed/', views.ShortVideoFeedView.as_view(), name='short-video-feed'),

    # --- Streaming ---
    path('shorts/<uuid:pk>/stream/', views.ShortVideoStreamView.as_view(), name='short-video-stream'),

    # --- Engagement (Likes, Views, Shares) ---
    path('shorts/<uuid:pk>/like/', views.VideoLikeToggleView.as_view(), name='short-video-like'),
    path('shorts/<uuid:pk>/view/', views.VideoViewRecordView.as_view(), name='short-video-view'),
    path('shorts/<uuid:pk>/share/', views.VideoShareRecordView.as_view(), name='short-video-share'),

    # --- Comments & Replies ---
    # List top-level comments or create a new comment
    path('shorts/<uuid:pk>/comments/', views.VideoCommentListCreateView.as_view(), name='short-video-comments'),
    
    # List replies to a specific comment
    path(
        'shorts/<uuid:pk>/comments/<uuid:comment_pk>/replies/', 
        views.CommentRepliesListView.as_view(), 
        name='short-video-comment-replies'
    ),

    # --- Individual Comment Management (Edit/Delete) ---
    path('comments/<uuid:pk>/', views.CommentDetailView.as_view(), name='comment-detail'),
]