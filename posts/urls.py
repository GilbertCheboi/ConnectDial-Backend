from django.urls import path
from .views import PostListCreateView, PostDetailView, FollowingFeedView

urlpatterns = [
    path('', PostListCreateView.as_view(), name='post-list-create'),
    path('<int:pk>/', PostDetailView.as_view(), name='post-detail'),
    path('feed/following/', FollowingFeedView.as_view(), name='following-feed'),

]

