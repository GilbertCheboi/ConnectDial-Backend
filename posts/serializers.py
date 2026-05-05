from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.conf import settings
from .models import Post, Comment, Hashtag, PostLike, PostShare
from users.models import Follow, Profile, FanPreference

User = get_user_model()

# ──────────────────────────────────────────────────────────────────────
# MIXINS & UTILITIES
# ──────────────────────────────────────────────────────────────────────

class SupportLogicMixin:
    """
    Standardized logic for the 'Supports [Team]' badge.
    Used by both Posts and Comments.
    """
    def get_supporting_info(self, obj):
        # Determine the user (Post uses .author, Comment uses .user)
        user = getattr(obj, 'author', getattr(obj, 'user', None))
        if not user:
            return None
        
        # 1. Professional Neutrality Guard: News/Org accounts never show fan support[cite: 3]
        if hasattr(user, 'account_type') and user.account_type in ['news', 'organization']:
            return None 

        # 2. Identify the target league (from Post directly or via parent Post in Comments)
        target_league = getattr(obj, 'league', None)
        if not target_league and hasattr(obj, 'post'):
            target_league = obj.post.league

        # 3. Contextual Preference: Show team for the specific league of the post[cite: 3]
        if target_league:
            pref = user.fan_preferences.filter(league=target_league).select_related('team').first()
            if pref and pref.team:
                return {
                    "team_name": pref.team.name,
                    "team_logo": pref.team.logo.url if pref.team.logo else None,
                    "league_name": target_league.name,
                    "type": "contextual"
                }
            
        # 4. Global Fallback: Show the overall favorite team if no league context matches[cite: 3]
        if hasattr(user, 'favorite_team') and user.favorite_team:
            return {
                "team_name": user.favorite_team.name,
                "team_logo": user.favorite_team.logo.url if user.favorite_team.logo else None,
                "league_name": user.favorite_league.name if user.favorite_league else "Global",
                "type": "global"
            }
            
        return None


# ──────────────────────────────────────────────────────────────────────
# SERIALIZERS
# ──────────────────────────────────────────────────────────────────────

class HashtagSerializer(serializers.ModelSerializer):
    post_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Hashtag
        fields = ['id', 'name', 'post_count']


class PostSerializer(serializers.ModelSerializer, SupportLogicMixin):
    author_details = serializers.SerializerMethodField() 
    supporting_info = serializers.SerializerMethodField()          
    is_owner = serializers.SerializerMethodField()
    liked_by_me = serializers.SerializerMethodField()
    original_post = serializers.SerializerMethodField()

    # Metrics for Algorithm & UI[cite: 3, 6]
    likes_count = serializers.IntegerField(read_only=True, default=0)
    comments_count = serializers.IntegerField(read_only=True, default=0)
    reposts_count = serializers.IntegerField(read_only=True, default=0)
    view_count = serializers.IntegerField(read_only=True, default=0)

    # Media & League Details
    league_details = serializers.SerializerMethodField()
    team_details = serializers.SerializerMethodField()
    media_url = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            'id', 'author_details', 'content', 'is_short', 'post_type', 
            'media_file', 'media_url', 'video_status', 'duration',
            'league', 'league_details', 'team', 'team_details', 
            'supporting_info', 'likes_count', 'comments_count', 
            'reposts_count', 'view_count', 'liked_by_me', 
            'created_at', 'is_owner', 'original_post'
        ]
        read_only_fields = [
            'video_status', 'duration', 'view_count', 
            'likes_count', 'comments_count', 'reposts_count'
        ]

    def get_media_url(self, obj):
        """Ensures React Native receives a full absolute URI for videos/images[cite: 3]."""
        request = self.context.get('request')
        if obj.media_file:
            return request.build_absolute_uri(obj.media_file.url) if request else obj.media_file.url
        return None

    def get_is_owner(self, obj):
        request = self.context.get('request')
        return request.user == obj.author if request and request.user.is_authenticated else False

    def get_liked_by_me(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            # Efficiently check many-to-many relationship[cite: 3]
            return obj.likes.filter(user=request.user).exists()
        return False

    def get_league_details(self, obj):
        if obj.league:
            return {
                "id": obj.league.id,
                "name": obj.league.name,
                "logo": obj.league.logo.url if obj.league.logo else None
            }
        return None

    def get_team_details(self, obj):
        if obj.team:
            return {
                "id": obj.team.id,
                "name": obj.team.name,
                "logo": obj.team.logo.url if obj.team.logo else None
            }
        return None

    def get_original_post(self, obj):
        """Recursive serialization for Reposts/Quotes[cite: 3]."""
        if obj.parent_post:
            return PostSerializer(obj.parent_post, context=self.context).data
        return None

    def get_author_details(self, obj):
        user = obj.author
        profile = getattr(user, 'profile', None)
        request = self.context.get('request')
        
        profile_pic = None
        if profile and profile.profile_image:
            profile_pic = request.build_absolute_uri(profile.profile_image.url) if request else profile.profile_image.url

        is_following = False
        if request and request.user.is_authenticated and request.user != user:
            is_following = Follow.objects.filter(follower=request.user, followed=user).exists()

        return {
            "id": user.id,
            "username": user.username,
            "display_name": profile.display_name if profile and profile.display_name else user.username,
            "profile_pic": profile_pic,
            "is_following": is_following,
            "account_type": user.account_type, # 'fan', 'news', 'organization'[cite: 3]
            "badge_type": user.badge_type,     # 'official', 'pioneer', etc.
            "fan_badge": user.fan_badge,
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
        read_only_fields = ['created_at', 'is_owner', 'likes_count', 'liked_by_me']

    def get_author_details(self, obj):
        user = obj.user
        profile = getattr(user, 'profile', None)
        request = self.context.get('request')
        
        profile_pic = None
        if profile and profile.profile_image:
            profile_pic = request.build_absolute_uri(profile.profile_image.url) if request else profile.profile_image.url

        return {
            "id": user.id,
            "username": user.username,
            "display_name": profile.display_name if profile and profile.display_name else user.username,
            "profile_pic": profile_pic,
            "account_type": getattr(user, 'account_type', 'fan'), 
            "badge_type": getattr(user, 'badge_type', None),      
            "fan_badge": getattr(user, 'fan_badge', None),        
        }

    def get_is_owner(self, obj):
        request = self.context.get('request')
        return request.user == obj.user if request and request.user.is_authenticated else False

    def get_liked_by_me(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            # Assuming a CommentLike model related name is 'likes'[cite: 4]
            return obj.likes.filter(user=request.user).exists()
        return False

    def get_likes_count(self, obj):
        return obj.likes.count() if hasattr(obj, 'likes') else 0