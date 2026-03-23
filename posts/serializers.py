from rest_framework import serializers
from django.contrib.auth import get_user_model
from posts.models import Post, Comment
from users.models import FanPreference
User = get_user_model()
from users.models import Profile  # Import from the users app
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


# Assuming Post is imported from your models and SupportLogicMixin is available
class ParentPostSerializer(serializers.ModelSerializer, SupportLogicMixin):
    """
    Updated to include Team and League info for the Quote Box.
    """
    author_details = serializers.SerializerMethodField()
    supporting_info = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            'id', 'content', 'media_file', 'author_details', 
            'supporting_info', 'league', 'created_at'
        ]

    def get_author_details(self, obj):
        # 🚀 1. Updated for OneToOneField 'profile'
        try:
            profile = obj.author.profile
        except AttributeError:
            profile = None

        request = self.context.get('request')
        profile_pic = None
        
        # 2. Handle Profile Picture URI
        if profile and profile.profile_image:
            if request:
                profile_pic = request.build_absolute_uri(profile.profile_image.url)
            else:
                profile_pic = profile.profile_image.url
            
        return {
            "id": obj.author.id,
            "username": obj.author.username,
            "display_name": profile.display_name if profile and profile.display_name else obj.author.username,
            "profile_pic": profile_pic,
        }
    # The SupportLogicMixin handles get_supporting_info automatically 
    # as long as it's included in the class definition.

from users.models import Follow  # Import your Follow model

class PostSerializer(serializers.ModelSerializer, SupportLogicMixin):
    author_details = serializers.SerializerMethodField() 
    supporting_info = serializers.SerializerMethodField()          
    is_owner = serializers.SerializerMethodField()
    likes_count = serializers.IntegerField(read_only=True, default=0)
    comments_count = serializers.IntegerField(read_only=True, default=0)
    liked_by_me = serializers.SerializerMethodField()
    reposts_count = serializers.IntegerField(read_only=True, default=0)
    original_post = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            'id', 'author_details', 'content', 'is_short', 'post_type', 'media_file',
            'league', 'supporting_info', 'likes_count', 'comments_count', 'reposts_count',
            'liked_by_me', 'created_at', 'is_owner', 'original_post'
        ]

    def get_is_owner(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.author == request.user
        return False

    def get_liked_by_me(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.likes.filter(user=request.user).exists()
        return False

    def get_original_post(self, obj):
        if obj.parent_post:
            return ParentPostSerializer(obj.parent_post, context=self.context).data
        return None

    def get_author_details(self, obj):
        """
        Includes Follow status so the PostCard can render the 'Follow' button.
        """
        # 🚀 1. Access the profile directly via the new 'profile' related_name
        try:
            profile = obj.author.profile
        except AttributeError:
            profile = None
            
        request = self.context.get('request')
        profile_pic = None
        is_following = False
        
        # 2. Handle Profile Picture URI
        if profile and profile.profile_image:
            if request:
                # Ensures React Native receives the full http:// URL
                profile_pic = request.build_absolute_uri(profile.profile_image.url)
            else:
                profile_pic = profile.profile_image.url

        # 3. Check Follow Status for the logged-in user
        if request and request.user.is_authenticated:
            # 🚀 IMPORT FOLLOW HERE to avoid Circular Import and Path errors
            from users.models import Follow 
            
            if request.user != obj.author:
                is_following = Follow.objects.filter(
                    follower=request.user, 
                    followed=obj.author
                ).exists()

        return {
            "id": obj.author.id,
            "username": obj.author.username,
            "display_name": profile.display_name if profile and profile.display_name else obj.author.username,
            "profile_pic": profile_pic,
            "is_following": is_following,
            "followers_count": obj.author.followers.count(),
        }



class CommentSerializer(serializers.ModelSerializer, SupportLogicMixin):
    """
    Full Comment Serializer with nested author details, 
    support logic for teams/leagues, and like/owner status.
    """
    # author_details uses UserMiniSerializer (ensure it's defined above this)
    author_details = UserMiniSerializer(source='user', read_only=True)
    
    # PrimaryKeyRelatedField for the parent post
    post = serializers.PrimaryKeyRelatedField(read_only=True)
    
    # SerializerMethodFields (Handled by the methods below or the Mixin)
    supporting_info = serializers.SerializerMethodField()
    is_owner = serializers.SerializerMethodField()
    liked_by_me = serializers.SerializerMethodField()
    likes_count = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = [
            'id', 
            'post', 
            'author_details', 
            'content', 
            'supporting_info', 
            'created_at', 
            'is_owner', 
            'likes_count', 
            'liked_by_me'
        ]

    def get_is_owner(self, obj):
        """Checks if the logged-in user wrote this comment."""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.user == request.user
        return False

    def get_liked_by_me(self, obj):
        """Checks if the logged-in user has liked this specific comment."""
        request = self.context.get("request")
        # Ensure your Comment model has a 'likes' related_name or check for the attribute
        if request and request.user.is_authenticated and hasattr(obj, 'likes'):
            return obj.likes.filter(user=request.user).exists()
        return False

    def get_likes_count(self, obj):
        """Returns the total number of likes for the comment."""
        if hasattr(obj, 'likes'):
            return obj.likes.count()
        return 0

    # Note: get_supporting_info is NOT defined here because 
    # it is being inherited automatically from SupportLogicMixin.