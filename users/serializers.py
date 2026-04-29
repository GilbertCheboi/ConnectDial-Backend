from rest_framework import serializers
from leagues.models import League, Team
from .models import (
    User,
    FanPreference,
    Profile,
    Follow,
)


# ========================= FAN PREFERENCE =========================

class FanPreferenceSerializer(serializers.ModelSerializer):
    league_name = serializers.ReadOnlyField(source='league.name')
    team_name   = serializers.ReadOnlyField(source='team.name')

    class Meta:
        model  = FanPreference
        fields = ['league', 'team', 'league_name', 'team_name']


# ========================= USER =========================

class UserSerializer(serializers.ModelSerializer):
    fan_preferences = FanPreferenceSerializer(many=True, read_only=True)
    is_onboarded    = serializers.SerializerMethodField()
    is_pioneer      = serializers.BooleanField(read_only=True)

    class Meta:
        model  = User
        fields = [
            'id',
            'username',
            'email',
            'auth_provider',
            'account_type',
            'badge_type',
            'fan_badge',
            'favorite_team',
            'favorite_league',
            'fan_preferences',
            'is_onboarded',
            'two_fa_enabled',
            'is_pioneer',
            #'is_bot',
        ]

    def get_is_onboarded(self, obj):
        if obj.account_type in ['news', 'organization']:
            return True
        return FanPreference.objects.filter(user=obj).exists()


# ========================= ONBOARDING =========================

class OnboardingSerializer(serializers.ModelSerializer):
    account_type    = serializers.ChoiceField(choices=User.ACCOUNT_TYPES)
    fan_preferences = FanPreferenceSerializer(many=True, required=False)

    class Meta:
        model  = User
        fields = ['account_type', 'fan_preferences']

    def validate(self, data):
        account_type = data.get('account_type')
        preferences  = data.get('fan_preferences', [])

        if account_type == 'fan':
            if not preferences:
                raise serializers.ValidationError('Fan accounts must select at least one favorite team.')
            for fp in preferences:
                if not fp.get('team'):
                    raise serializers.ValidationError('Fan accounts must select a team for each league.')

        if account_type in ['news', 'organization']:
            if not preferences:
                raise serializers.ValidationError(
                    f"{account_type.title()} accounts must select at least one league."
                )

        # Check for duplicate leagues
        if preferences:
            leagues = [
                fp['league'].id if isinstance(fp['league'], League) else fp['league']
                for fp in preferences
            ]
            if len(leagues) != len(set(leagues)):
                raise serializers.ValidationError('You can only select one team per league.')

        return data

    def create(self, validated_data):
        user          = self.context['request'].user
        account_type  = validated_data.get('account_type', user.account_type)
        fan_prefs_data = validated_data.get('fan_preferences', [])

        user.account_type = account_type

        # Clear old preferences
        FanPreference.objects.filter(user=user).delete()

        if account_type == 'fan':
            user.favorite_team   = None
            user.favorite_league = None
            for fp in fan_prefs_data:
                FanPreference.objects.create(user=user, league=fp['league'], team=fp['team'])
            if fan_prefs_data:
                primary              = fan_prefs_data[0]
                user.favorite_team   = primary['team']
                user.favorite_league = primary['league']
                user.fan_badge       = f"{primary['team'].name} Fan"

        else:  # news or organization
            for fp in fan_prefs_data:
                FanPreference.objects.create(user=user, league=fp['league'], team=fp.get('team'))
            if account_type == 'news':
                user.fan_badge = (
                    'Official Media'
                    if getattr(user, 'badge_type', None) == 'official'
                    else 'Awaiting Partnership'
                )

        user.save()
        return user


# ========================= PROFILE =========================

class ProfileSerializer(serializers.ModelSerializer):
    username        = serializers.ReadOnlyField(source='user.username')
    fan_preferences = FanPreferenceSerializer(source='user.fan_preferences', many=True, read_only=True)
    is_following    = serializers.SerializerMethodField()
    followers_count = serializers.SerializerMethodField()
    following_count = serializers.SerializerMethodField()
    user_id         = serializers.ReadOnlyField(source='user.id')

    class Meta:
        model  = Profile
        fields = [
            'id',
            'user_id',
            'display_name',
            'bio',
            'profile_image',
            'banner_image',
            'fcm_token',
            'username',
            'fan_preferences',
            'is_following',
            'followers_count',
            'following_count',
        ]

    def get_is_following(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return Follow.objects.filter(follower=request.user, followed=obj.user).exists()
        return False

    def get_followers_count(self, obj):
        return obj.user.followers.count()

    def get_following_count(self, obj):
        return obj.user.following.count()


# ========================= 2FA =========================

class TwoFAToggleSerializer(serializers.Serializer):
    enable = serializers.BooleanField()


# ========================= CUSTOM LOGIN SERIALIZER =========================

from dj_rest_auth.serializers import LoginSerializer

class CustomLoginSerializer(LoginSerializer):
    """
    Extends dj-rest-auth's LoginSerializer.
    The user payload shape is controlled via REST_AUTH['USER_DETAILS_SERIALIZER']
    pointing to UserSerializer — no overrides needed here.
    """
    pass