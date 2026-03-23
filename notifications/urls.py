from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import NotificationViewSet

# 🚀 Use a router to handle the standard GET, POST, and our custom 'mark-all-read'
router = DefaultRouter()
router.register(r'', NotificationViewSet, basename='notification')

urlpatterns = [
    path('', include(router.urls)),
]