from rest_framework import serializers
from .models import UserFollow, TeamFollow, LeagueFollow


class UserFollowSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserFollow
        fields = ['id', 'follower', 'following', 'created_at']
        read_only_fields = ['follower', 'created_at']


class TeamFollowSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeamFollow
        fields = ['id', 'team', 'created_at']
        read_only_fields = ['created_at']


class LeagueFollowSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeagueFollow
        fields = ['id', 'league', 'created_at']
        read_only_fields = ['created_at']

