from rest_framework import serializers
from .models import ShortVideo

class ShortVideoSerializer(serializers.ModelSerializer):
    author_username = serializers.CharField(source='author.username', read_only=True)
    league_name = serializers.CharField(source='league.name', read_only=True)
    team_name = serializers.CharField(source='team.name', read_only=True)

    likes_count = serializers.IntegerField(read_only=True)
    comments_count = serializers.IntegerField(read_only=True)
    shares_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = ShortVideo
        fields = [
            'id',
            'author_username',
            'video',
            'caption',
            'league_name',
            'team_name',
            'likes_count',
            'comments_count',
            'shares_count',
            'created_at',
        ]

