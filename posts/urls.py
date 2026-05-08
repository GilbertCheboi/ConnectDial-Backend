from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    PostViewSet, 
    CommentViewSet, 
    ShortVideoViewSet, 
    HashtagViewSet, 
    
)

router = DefaultRouter()

# 🚀 Specific endpoints first
router.register(r'shorts', ShortVideoViewSet, basename='short')
router.register(r'comments', CommentViewSet, basename='comment')
router.register(r'hashtags', HashtagViewSet, basename='hashtag')

# 🚀 Catch-all PostViewSet last
router.register(r'', PostViewSet, basename='post') 

urlpatterns = [
    # APIView goes here
    path('', include(router.urls)),
]