from rest_framework import serializers
from .models import User, FanPreference, Profile
from leagues.models import League, Team
from .models import Follow  # Ensure you have a Follow model for the following logic


class FanPreferenceSerializer(serializers.ModelSerializer):
    league_name = serializers.ReadOnlyField(source='league.name')
    team_name = serializers.ReadOnlyField(source='team.name')

    class Meta:
        model = FanPreference
        fields = ['league', 'team', 'league_name', 'team_name']


class UserSerializer(serializers.ModelSerializer):
    fan_preferences = FanPreferenceSerializer(many=True, read_only=True)
    favorite_team = serializers.PrimaryKeyRelatedField(read_only=True)
    favorite_league = serializers.PrimaryKeyRelatedField(read_only=True)
    is_onboarded = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'email',
            'auth_provider',
            'account_type',
            'badge_type',
            'favorite_team',
            'favorite_league',
            'fan_badge',
            'fan_preferences',
            'is_onboarded',
        ]

    def get_is_onboarded(self, obj):
        if obj.account_type in ['news', 'organization']:
            return True

        return FanPreference.objects.filter(user=obj).exists()


class OnboardingSerializer(serializers.ModelSerializer):
    account_type = serializers.ChoiceField(choices=User.ACCOUNT_TYPES)
    fan_preferences = FanPreferenceSerializer(many=True, required=False)

    class Meta:
        model = User
        fields = ['account_type', 'fan_preferences']

    def validate(self, data):
        account_type = data.get('account_type')
        preferences = data.get('fan_preferences', [])

        if account_type == 'fan':
            if not preferences:
                raise serializers.ValidationError(
                    "Fan accounts must select at least one favorite team."
                )
            # Validate that fan accounts have teams
            for fp in preferences:
                if not fp.get('team'):
                    raise serializers.ValidationError(
                        "Fan accounts must select a team for each league."
                    )

        if account_type in ['news', 'organization']:
            if not preferences:
                raise serializers.ValidationError(
                    f"{account_type.title()} accounts must select at least one league."
                )
            # For news/org, team is optional
            pass

        if preferences:
            leagues = [
                fp['league'].id if isinstance(fp['league'], League) else fp['league']
                for fp in preferences
            ]
            if len(leagues) != len(set(leagues)):
                raise serializers.ValidationError("You can only select one team per league.")

        return data

    def create(self, validated_data):
        user = self.context['request'].user
        account_type = validated_data.get('account_type', user.account_type)
        fan_preferences_data = validated_data.get('fan_preferences', [])

        user.account_type = account_type

        if account_type == 'fan':
            user.favorite_team = None
            user.favorite_league = None
            FanPreference.objects.filter(user=user).delete()

            for fp in fan_preferences_data:
                FanPreference.objects.create(
                    user=user,
                    league=fp['league'],
                    team=fp['team']
                )

            if fan_preferences_data:
                primary_pref = fan_preferences_data[0]
                user.favorite_team = primary_pref['team']
                user.favorite_league = primary_pref['league']
                user.fan_badge = f"{primary_pref['team'].name} Fan"

        else:
            # For news/organization accounts, create fan_preferences with leagues but no teams
            FanPreference.objects.filter(user=user).delete()
            user.favorite_team = None
            user.favorite_league = None
            
            for fp in fan_preferences_data:
                FanPreference.objects.create(
                    user=user,
                    league=fp['league'],
                    team=fp.get('team')  # Allow team to be None
                )
            
            if account_type == 'news' and user.badge_type == 'official':
                user.fan_badge = 'Official Media'
            elif account_type == 'news':
                user.fan_badge = 'Awaiting Partnership'

        user.save()
        return user

    def update(self, instance, validated_data):
        return self.create(validated_data)


class ProfileSerializer(serializers.ModelSerializer):
    # 🚀 Add these lines to pull data from the related User model
    username = serializers.ReadOnlyField(source='user.username')
    fan_preferences = FanPreferenceSerializer(source='user.fan_preferences', many=True, read_only=True)
    is_following = serializers.SerializerMethodField()
    followers_count = serializers.SerializerMethodField()
    following_count = serializers.SerializerMethodField()
    user_id = serializers.ReadOnlyField(source='user.id')
    # Remove the SerializerMethodField for profile_image to allow file uploads
    class Meta:
        model = Profile
        # 🚀 Add 'username' and 'fan_preferences' to the fields
        fields = ['id', 'user_id', 'display_name', 'bio', 'profile_image', 'banner_image', 'fcm_token', 'username', 'fan_preferences', 'is_following', 'followers_count', 'following_count']

    def get_is_following(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            # Check if the logged-in user follows the owner of THIS profile
            return Follow.objects.filter(follower=request.user, followed=obj.user).exists()
        return False

    def get_followers_count(self, obj):
        return obj.user.followers.count()

    def get_following_count(self, obj):
        return obj.user.following.count()

from dj_rest_auth.serializers import LoginSerializer

class CustomLoginSerializer(LoginSerializer):
    # This is the "Delivery Man" method. 
    # It tells Django: "When the login is successful, use UserSerializer 
    # to pack the user data into the JSON response."
    def get_response_serializer(self):
        return UserSerializer