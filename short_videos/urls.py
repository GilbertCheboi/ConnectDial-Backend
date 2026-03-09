from django.urls import path
from .views import ShortVideoFeedView

urlpatterns = [
    path('feed/', ShortVideoFeedView.as_view(), name='short-video-feed'),
]

