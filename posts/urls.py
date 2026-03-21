# posts/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PostViewSet, CommentViewSet, ShortVideoViewSet

router = DefaultRouter()

# 🚀 STEP 1: Register specific endpoints FIRST
router.register(r'shorts', ShortVideoViewSet, basename='short')
router.register(r'comments', CommentViewSet, basename='comment')

# 🚀 STEP 2: Register the catch-all PostViewSet LAST
router.register(r'', PostViewSet, basename='post') 

urlpatterns = [
    path('', include(router.urls)),
]