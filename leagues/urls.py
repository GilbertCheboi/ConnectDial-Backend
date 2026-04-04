# leagues/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import LeagueViewSet, TeamViewSet

router = DefaultRouter()

# LeagueViewSet has a .queryset, so it doesn't strictly need a basename, 
# but it's good practice to add it.
router.register(r'leagues', LeagueViewSet, basename='league')

# 🚀 THE FIX: TeamViewSet uses get_queryset(), so it REQUIRES a basename
router.register(r'teams', TeamViewSet, basename='team')

urlpatterns = [
    path('', include(router.urls)),
]