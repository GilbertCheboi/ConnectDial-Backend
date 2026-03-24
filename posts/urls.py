from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PostViewSet, CommentViewSet, ShortVideoViewSet, HashtagViewSet # 🚀 Added HashtagViewSet

router = DefaultRouter()

# 🚀 STEP 1: Register specific endpoints
router.register(r'shorts', ShortVideoViewSet, basename='short')
router.register(r'comments', CommentViewSet, basename='comment')
router.register(r'hashtags', HashtagViewSet, basename='hashtag') # 🚀 Added this before the catch-all

# 🚀 STEP 2: Register the catch-all PostViewSet LAST
router.register(r'', PostViewSet, basename='post') 

urlpatterns = [
    path('', include(router.urls)),
]