from django.urls import path
from .views import TrendingPostsView

urlpatterns = [
    path('posts/', TrendingPostsView.as_view(), name='trending-posts'),
]

