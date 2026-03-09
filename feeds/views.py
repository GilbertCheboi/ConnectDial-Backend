from rest_framework import generics, permissions
from .models import UserFollow, TeamFollow, LeagueFollow
from .serializers import (
    UserFollowSerializer,
    TeamFollowSerializer,
    LeagueFollowSerializer
)


class FollowUserView(generics.CreateAPIView):
    serializer_class = UserFollowSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(follower=self.request.user)


class FollowTeamView(generics.CreateAPIView):
    serializer_class = TeamFollowSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class FollowLeagueView(generics.CreateAPIView):
    serializer_class = LeagueFollowSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

