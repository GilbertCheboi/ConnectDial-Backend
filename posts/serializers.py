from rest_framework import serializers
from posts.models import Post, PostLike, PostShare, Comment


class PostSerializer(serializers.ModelSerializer):

    # Author identity
    author_username = serializers.CharField(source='author.username', read_only=True)
    author_fan_badge = serializers.CharField(source='author.fan_badge', read_only=True)

    # League / Team names
    league_name = serializers.CharField(source='league.name', read_only=True)
    team_name = serializers.CharField(source='team.name', read_only=True)

    # Engagement counts
    likes_count = serializers.IntegerField(source='likes.count', read_only=True)
    comments_count = serializers.IntegerField(source='comments.count', read_only=True)
    shares_count = serializers.IntegerField(source='shares.count', read_only=True)

    liked_by_me = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            'id',
            'author',
            'author_username',
            'author_fan_badge',

            'content',
            'post_type',
            'media_file',

            'league',
            'league_name',

            'team',
            'team_name',

            'likes_count',
            'comments_count',
            'shares_count',
            'liked_by_me',

            'created_at',
            'updated_at',
        ]

        read_only_fields = [
            'id',
            'author',
            'author_username',
            'author_fan_badge',
            'league_name',
            'team_name',
            'likes_count',
            'comments_count',
            'shares_count',
            'liked_by_me',
            'created_at',
            'updated_at',
        ]

    def get_liked_by_me(self, obj):
        request = self.context.get("request")

        if request and request.user.is_authenticated:
            return obj.likes.filter(user=request.user).exists()

        return False


# ------------------------------------
# Comment Serializer
# ------------------------------------

class CommentSerializer(serializers.ModelSerializer):

    author_username = serializers.CharField(source='user.username', read_only=True)
    author_fan_badge = serializers.CharField(source='user.fan_badge', read_only=True)

    league_name = serializers.SerializerMethodField()
    team_name = serializers.SerializerMethodField()

    likes_count = serializers.IntegerField(source='likes.count', read_only=True)
    liked_by_me = serializers.SerializerMethodField()

    class Meta:
        model = Comment

        fields = [
            'id',
            'post',
            'user',

            'author_username',
            'author_fan_badge',

            'content',

            'league_name',
            'team_name',

            'likes_count',
            'liked_by_me',

            'created_at',
        ]

        read_only_fields = [
            'id',
            'user',
            'author_username',
            'author_fan_badge',
            'league_name',
            'team_name',
            'likes_count',
            'liked_by_me',
            'created_at',
        ]

    def get_league_name(self, obj):
        if obj.user.favorite_league:
            return obj.user.favorite_league.name
        return None

    def get_team_name(self, obj):
        if obj.user.favorite_team:
            return obj.user.favorite_team.name
        return None

    def get_liked_by_me(self, obj):
        request = self.context.get("request")

        if request and request.user.is_authenticated:
            return obj.likes.filter(user=request.user).exists()

        return False