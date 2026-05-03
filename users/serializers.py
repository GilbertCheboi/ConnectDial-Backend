from rest_framework import serializers
from .models import User, FanPreference, Profile
from leagues.models import League, Team
from .models import Follow
from django.contrib.auth import authenticate


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
    append_mode = serializers.BooleanField(default=False, required=False)   # ← NEW

    class Meta:
        model = User
        fields = ['account_type', 'fan_preferences', 'append_mode']

    def validate(self, data):
        account_type = data.get('account_type')
        preferences = data.get('fan_preferences', [])
        append_mode = data.get('append_mode', False)

        if account_type == 'fan':
            if not preferences and not append_mode:
                raise serializers.ValidationError(
                    "Fan accounts must select at least one favorite team."
                )
            for fp in preferences:
                if not fp.get('team'):
                    raise serializers.ValidationError(
                        "Each league must have a selected team for fan accounts."
                    )

        # For news/organization accounts
        elif account_type in ['news', 'organization']:
            if not preferences and not append_mode:
                raise serializers.ValidationError(
                    f"{account_type.title()} accounts must select at least one league."
                )

        # Check for duplicate leagues
        if preferences:
            leagues = [fp['league'] for fp in preferences if fp.get('league')]
            if len(leagues) != len(set(leagues)):
                raise serializers.ValidationError("You can only select one team per league.")

        return data

    def create(self, validated_data):
        user = self.context['request'].user
        account_type = validated_data.get('account_type', user.account_type)
        preferences_data = validated_data.get('fan_preferences', [])
        append_mode = validated_data.get('append_mode', False)

        user.account_type = account_type

        # Handle append_mode (for editing preferences)
        if append_mode:
            # Only add new preferences, don't delete existing ones
            existing_leagues = set(FanPreference.objects.filter(user=user).values_list('league_id', flat=True))
            for fp in preferences_data:
                if fp['league'].id not in existing_leagues:
                    FanPreference.objects.create(
                        user=user,
                        league=fp['league'],
                        team=fp.get('team')
                    )
        else:
            # Full replace (first time onboarding)
            FanPreference.objects.filter(user=user).delete()
            user.favorite_team = None
            user.favorite_league = None

            for fp in preferences_data:
                FanPreference.objects.create(
                    user=user,
                    league=fp['league'],
                    team=fp.get('team')
                )

            # Set primary team/league for fans
            if account_type == 'fan' and preferences_data:
                primary = preferences_data[0]
                user.favorite_team = primary.get('team')
                user.favorite_league = primary.get('league')
                user.fan_badge = f"{primary['team'].name} Fan" if primary.get('team') else None

        # Special badge logic for news/org
        if account_type == 'news':
            user.fan_badge = 'Official Media' if user.badge_type == 'official' else 'Awaiting Partnership'

        user.save()
        return user

    def update(self, instance, validated_data):
        """Handle both create and update the same way"""
        return self.create(validated_data)


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
            'id', 'user_id', 'display_name', 'bio',
            'profile_image', 'banner_image', 'fcm_token',
            'username', 'fan_preferences',
            'is_following', 'followers_count', 'following_count',
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


# ─────────────────────────────────────────────
# CUSTOM LOGIN SERIALIZER
# ─────────────────────────────────────────────

from dj_rest_auth.serializers import LoginSerializer

class CustomLoginSerializer(LoginSerializer):
    # Accept username OR email so the frontend can send either.
    # dj-rest-auth's default enforces email+password — we override that here.
    username = serializers.CharField(required=False, allow_blank=True)
    email    = serializers.EmailField(required=False, allow_blank=True)

    def validate(self, attrs):
        username = attrs.get('username', '').strip()
        email    = attrs.get('email', '').strip()
        password = attrs.get('password', '')

        if not password:
            raise serializers.ValidationError(
                {'password': 'Password is required.'},
                code='authorization',
            )

        # Resolve identifier: prefer username, fall back to email
        identifier = username or email

        if not identifier:
            raise serializers.ValidationError(
                {'username': 'Username or email is required.'},
                code='authorization',
            )

        # If identifier looks like an email, try email-based auth first
        user = None
        if '@' in identifier:
            try:
                matched = User.objects.get(email__iexact=identifier)
                user = authenticate(
                    request=self.context.get('request'),
                    username=matched.username,
                    password=password,
                )
            except User.DoesNotExist:
                pass

        # Fall back to direct username auth
        if user is None:
            user = authenticate(
                request=self.context.get('request'),
                username=identifier,
                password=password,
            )

        if user is None:
            raise serializers.ValidationError(
                {'non_field_errors': ['Invalid username/email or password.']},
                code='authorization',
            )

        if not user.is_active:
            raise serializers.ValidationError(
                {'non_field_errors': ['This account has been disabled.']},
                code='authorization',
            )

        attrs['user'] = user
        return attrs