from rest_framework import serializers
from django.contrib.auth import get_user_model
from posts.models import Post, Comment, Hashtag
from users.models import FanPreference
User = get_user_model()
from users.models import Profile  # Import from the users app
class UserMiniSerializer(serializers.ModelSerializer):
    """Basic author info for the header"""
    class Meta:
        model = User
        fields = ['id', 'username', 'account_type', 'badge_type', 'fan_badge']

class SupportLogicMixin:
    def get_supporting_info(self, obj):
        author = obj.author if hasattr(obj, 'author') else obj.user
        
        # 1. FIX: Check the specific author's account type, not the User class
        if hasattr(author, 'account_type') and author.account_type in ['news', 'organization']:
            return None 

        target_league = getattr(obj, 'league', None)
        if not target_league and hasattr(obj, 'post'):
            target_league = obj.post.league

        if not target_league:
            return None

        pref = author.fan_preferences.filter(
            league=target_league
        ).select_related('team', 'league').first()

        # 2. FIX: Ensure BOTH the preference and the team exist before accessing .name
        if pref and pref.team:
            return {
                "team_name": pref.team.name,
                "league_name": pref.league.name,
                "text": f"Supports {pref.team.name}"
            }
            
        return None

# Assuming Post is imported from your models and SupportLogicMixin is available

class ParentPostSerializer(serializers.ModelSerializer, SupportLogicMixin):
    """
    Updated to include all 5 Badge Types and Account Type logic 
    for the Quote Box / Repost UI.
    """
    author_details = serializers.SerializerMethodField()
    supporting_info = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            'id', 'content', 'media_file', 'author_details', 
            'supporting_info', 'league', 'created_at'
        ]

    def get_supporting_info(self, obj):
        """
        Uses the same logic as the main PostSerializer:
        Blocks fan support for News/Org accounts to prevent 'Global' fallback.
        """
        user = obj.author
        
        # 1. Professional Neutrality Guard
        if user.account_type in ['news', 'organization']:
            return None

        # 2. League Specific Logic (e.g., NBA, F1)
        if obj.league:
            pref = user.fan_preferences.filter(league=obj.league).first()
            if pref and pref.team:
                return {
                    "team_name": pref.team.name,
                    "team_logo": pref.team.logo.url if pref.team.logo else None,
                    "type": "contextual"
                }
        
        # 3. Global Fan Fallback
        if user.favorite_team:
            return {
                "team_name": user.favorite_team.name,
                "team_logo": user.favorite_team.logo.url if user.favorite_team.logo else None,
                "type": "global"
            }

        return None

    def get_author_details(self, obj):
        """
        Includes account_type and badge_type so the Quote Box 
        can show the Gold Check or Pioneer Rocket.
        """
        try:
            profile = obj.author.profile
        except AttributeError:
            profile = None

        request = self.context.get('request')
        profile_pic = None
        
        # Handle Profile Picture URI
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
            # 🚀 Essential for the React Native badge logic
            "account_type": obj.author.account_type, # 'fan', 'news', 'organization'
            "badge_type": obj.author.badge_type,     # 'official', 'pioneer', etc.
            "fan_badge": obj.author.fan_badge,
        }
    # The SupportLogicMixin handles get_supporting_info automatically 
    # as long as it's included in the class definition.

from users.models import Follow  # Import your Follow model

from rest_framework import serializers
from django.conf import settings
from users.models import Follow, Profile

class PostSerializer(serializers.ModelSerializer):
    author_details = serializers.SerializerMethodField() 
    supporting_info = serializers.SerializerMethodField()          
    is_owner = serializers.SerializerMethodField()
    likes_count = serializers.IntegerField(read_only=True, default=0)
    comments_count = serializers.IntegerField(read_only=True, default=0)
    liked_by_me = serializers.SerializerMethodField()
    reposts_count = serializers.IntegerField(read_only=True, default=0)
    original_post = serializers.SerializerMethodField()

    # Details for the Shorts Feed UI / Media Overlays
    league_details = serializers.SerializerMethodField()
    team_details = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            'id', 'author_details', 'content', 'is_short', 'post_type', 'media_file',
            'league', 'league_details', 'team', 'team_details', 'supporting_info', 
            'likes_count', 'comments_count', 'reposts_count', 'liked_by_me', 
            'created_at', 'is_owner', 'original_post'
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

    def get_league_details(self, obj):
        """ Returns name and ID for the league badge (e.g., PL, NBA) """
        if obj.league:
            return {
                "id": obj.league.id,
                "name": obj.league.name,
                "logo": obj.league.logo.url if obj.league.logo else None
            }
        return None

    def get_team_details(self, obj):
        """ Returns specific team info if the post is tagged to a team """
        if obj.team:
            return {
                "id": obj.team.id,
                "name": obj.team.name,
                "logo": obj.team.logo.url if obj.team.logo else None
            }
        return None

    def get_supporting_info(self, obj):
        """
        Logic for 'Supports [Team]' badge. 
        1. Professional accounts (News/Org) -> Always None.
        2. Fan Post with specific League -> Show League Team.
        3. Fan Post without League -> Show Global Favorite.
        """
        user = obj.author
        
        # 🚀 CRITICAL FIX: Block Professional accounts immediately.
        # This prevents them from ever hitting the "Global" fallback.
        if user.account_type in ['news', 'organization']:
            return None

        # ---------------------------------------------------------
        # Everything below only runs for 'fan' account types
        # ---------------------------------------------------------

        # 1. SPECIFIC LEAGUE CHECK 
        # (e.g., If the post is NBA, show their NBA team)
        if obj.league:
            # We use .filter().first() to avoid DoesNotExist errors
            pref = user.fan_preferences.filter(league=obj.league).first()
            if pref and pref.team:
                return {
                    "team_name": pref.team.name,
                    "team_logo": pref.team.logo.url if pref.team.logo else None,
                    "league_name": obj.league.name,
                    "type": "contextual" 
                }
        
        # 2. GLOBAL FALLBACK
        # (Only shows if they are a fan and the post isn't league-specific)
        if user.favorite_team:
            return {
                "team_name": user.favorite_team.name,
                "team_logo": user.favorite_team.logo.url if user.favorite_team.logo else None,
                "league_name": user.favorite_league.name if user.favorite_league else "Global",
                "type": "global"
            }

        return None

    def get_original_post(self, obj):
        if obj.parent_post:
            # Recursive call for reposts
            return PostSerializer(obj.parent_post, context=self.context).data
        return None

    def get_author_details(self, obj):
        """
        Comprehensive author info including trust badges and follow status.
        """
        try:
            profile = obj.author.profile
        except AttributeError:
            profile = None
            
        request = self.context.get('request')
        profile_pic = None
        is_following = False
        
        # Handle Absolute Media URIs for React Native
        if profile and profile.profile_image:
            if request:
                profile_pic = request.build_absolute_uri(profile.profile_image.url)
            else:
                profile_pic = profile.profile_image.url

        # Follow logic
        if request and request.user.is_authenticated and request.user != obj.author:
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
            # Status Flags for UI rendering
            "account_type": obj.author.account_type, # 'fan', 'news', 'organization'
            "badge_type": obj.author.badge_type,     # 'pioneer', 'superfan', 'official'
            "fan_badge_text": obj.author.fan_badge,  # e.g., 'Awaiting Partnership'
        }


class CommentSerializer(serializers.ModelSerializer, SupportLogicMixin):
    author_details = serializers.SerializerMethodField()
    supporting_info = serializers.SerializerMethodField()
    is_owner = serializers.SerializerMethodField()
    liked_by_me = serializers.SerializerMethodField()
    likes_count = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = [
            'id', 'post', 'author_details', 'content', 
            'supporting_info', 'created_at', 'is_owner', 
            'likes_count', 'liked_by_me'
        ]
        # 🚀 Only include fields that the user SHOULD NOT be able to change
        # 'content' and 'post' must be excluded from here to be writeable
        read_only_fields = [
            'id', 
            'author_details', 
            'supporting_info', 
            'created_at', 
            'is_owner', 
            'likes_count', 
            'liked_by_me'
        ]

    def get_author_details(self, obj):
        user = obj.user
        profile = getattr(user, 'profile', None)
        request = self.context.get('request')
        
        profile_pic = None
        if profile and profile.profile_image:
            # build_absolute_uri is critical for images to show on React Native
            profile_pic = request.build_absolute_uri(profile.profile_image.url) if request else profile.profile_image.url

        return {
            "id": user.id,
            "username": user.username,
            "display_name": profile.display_name if profile and profile.display_name else user.username,
            "profile_pic": profile_pic,
            # 🚀 These fields are required for your UI badge logic
            "account_type": getattr(user, 'account_type', 'fan'), 
            "badge_type": getattr(user, 'badge_type', None),      
            "fan_badge": getattr(user, 'fan_badge', None),        
        }

    def get_is_owner(self, obj):
        request = self.context.get('request')
        return request.user == obj.user if request and request.user.is_authenticated else False

    def get_liked_by_me(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated and hasattr(obj, 'likes'):
            return obj.likes.filter(user=request.user).exists()
        return False

    def get_likes_count(self, obj):
        return obj.likes.count() if hasattr(obj, 'likes') else 0


class HashtagSerializer(serializers.ModelSerializer):
    post_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Hashtag
        fields = ['id', 'name', 'post_count']




    # Note: get_supporting_info is NOT defined here because 
    # it is being inherited automatically from SupportLogicMixin.