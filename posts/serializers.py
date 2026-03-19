from rest_framework import serializers
from django.contrib.auth import get_user_model
from posts.models import Post, Comment
from users.models import FanPreference
User = get_user_model()

class UserMiniSerializer(serializers.ModelSerializer):
    """Basic author info for the header"""
    class Meta:
        model = User
        fields = ['id', 'username', 'fan_badge']

class SupportLogicMixin:
    """
    Reusable logic for both Posts and Comments to find which 
    team the user supports in the specific league of the content.
    """
    def get_supporting_info(self, obj):
        # 'obj' is either a Post or a Comment
        author = obj.author if hasattr(obj, 'author') else obj.user
        
        # We need the league of the post to filter the user's teams
        # If it's a comment, we look at the parent post's league
        target_league = getattr(obj, 'league', None)
        if not target_league and hasattr(obj, 'post'):
            target_league = obj.post.league

        if not target_league:
            return None

        # Look for the specific team this user picked for THIS league
        pref = author.fan_preferences.filter(league=target_league).select_related('team', 'league').first()
        
        if pref:
            return {
                "team_name": pref.team.name,
                "league_name": pref.league.name,
                "text": f"Supports {pref.team.name}"
            }
        return None

class PostSerializer(serializers.ModelSerializer, SupportLogicMixin):
    author_details = UserMiniSerializer(source='author', read_only=True)
    supporting_info = serializers.SerializerMethodField()
    
    likes_count = serializers.IntegerField(read_only=True, default=0)
    comments_count = serializers.IntegerField(read_only=True, default=0)
    liked_by_me = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            'id', 'author_details', 'content', 'post_type', 'media_file',
            'league', 'supporting_info', 'likes_count', 'comments_count', 
            'liked_by_me', 'created_at'
        ]

    def get_liked_by_me(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.likes.filter(user=request.user).exists()
        return False

class CommentSerializer(serializers.ModelSerializer, SupportLogicMixin):
    author_details = UserMiniSerializer(source='user', read_only=True)
    supporting_info = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = [
            'id', 'post', 'author_details', 'content', 
            'supporting_info', 'created_at'
        ]