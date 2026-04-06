from rest_framework import serializers
from posts.models import Post

class TrendingPostSerializer(serializers.ModelSerializer):
    author_username = serializers.CharField(source='author.username', read_only=True)
    author_account_type = serializers.CharField(source='author.account_type', read_only=True)
    author_badge_type = serializers.CharField(source='author.badge_type', read_only=True)
    author_fan_badge = serializers.CharField(source='author.fan_badge', read_only=True)
    league_name = serializers.CharField(source='league.name', read_only=True)
    team_name = serializers.CharField(source='team.name', read_only=True)

    likes_count = serializers.IntegerField(read_only=True)
    comments_count = serializers.IntegerField(read_only=True)
    shares_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Post
        fields = [
            'id',
            'author_username',
            'author_fan_badge',
            'content',
            'post_type',
            'media_file',
            'league_name',
            'team_name',
            'likes_count',
            'comments_count',
            'shares_count',
            'created_at',
        ]

