from rest_framework import serializers
from .models import User, FanPreference
from leagues.models import League, Team
from .models import Profile, Follow  # Ensure you have a Follow model for the following logic
# For returning existing preferences
# In Django serializers.py
class FanPreferenceSerializer(serializers.ModelSerializer):
    league_name = serializers.ReadOnlyField(source='league.name')
    team_name = serializers.ReadOnlyField(source='team.name')

    class Meta:
        model = FanPreference
        fields = ['league', 'team', 'league_name', 'team_name']

        
from rest_framework import serializers
from .models import FanPreference, Profile  # Ensure correct imports

class UserSerializer(serializers.ModelSerializer):
    fan_preferences = FanPreferenceSerializer(many=True, read_only=True)
    # This field tells the frontend if onboarding is complete
    is_onboarded = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'email',
            'auth_provider',
            'fan_badge',
            'fan_preferences',
            'is_onboarded' # Added this
        ]

    def get_is_onboarded(self, obj):
        """
        Logic: User is onboarded if they have:
        1. At least one FanPreference record.
        2. A Profile with a display_name (optional, but recommended).
        """
        has_prefs = FanPreference.objects.filter(user=obj).exists()
        
        # If you want to ensure they also finished the 'Create Profile' screen:
        # has_profile = Profile.objects.filter(user=obj).exclude(display_name="").exists()
        # return has_prefs and has_profile
        
        return has_prefs


class OnboardingSerializer(serializers.ModelSerializer):
    fan_preferences = FanPreferenceSerializer(many=True)

    class Meta:
        model = User  # Ensure your User model is linked here
        fields = ['fan_preferences'] # Add other fields as needed

    def validate(self, data):
        # Ensure one team per league
        leagues = [fp['league'].id if isinstance(fp['league'], League) else fp['league']
                   for fp in data['fan_preferences']]
        if len(leagues) != len(set(leagues)):
            raise serializers.ValidationError("You can only select one team per league.")
        return data

    def create(self, validated_data):
        # This MUST be indented inside the class
        user = self.context['request'].user
        fan_preferences_data = validated_data.pop('fan_preferences', [])

        # 1. Delete old preferences
        user.fan_preferences.all().delete()

        # 2. Save new preferences to the FanPreference table
        for fp in fan_preferences_data:
            FanPreference.objects.create(
                user=user,
                league=fp['league'],
                team=fp['team']
            )

        # 3. Update the main User model fields
        if fan_preferences_data:
            primary_pref = fan_preferences_data[0]
            user.favorite_team = primary_pref['team']
            user.favorite_league = primary_pref['league']
            user.fan_badge = f"{primary_pref['team'].name} Fan"
            user.save() 

        return user

    def update(self, instance, validated_data):
    # 1. Get the list of new preferences from the request
        new_preferences = validated_data.get('fan_preferences', [])
    
    # 2. Check the flag we sent from React Native
        append_mode = self.initial_data.get('append_mode', False)

    # 3. Handle the logic
        if not append_mode:
        # If NOT in append mode (Onboarding), clear old preferences first
               instance.fan_preferences.all().delete()

    # 4. Add the new ones
        for pref in new_preferences:
        # Logic to create or update the preference
        # e.g., FanPreference.objects.update_or_create(user=instance, league=pref['league'], defaults={'team': pref['team']})
          pass
        
        return instance

class ProfileSerializer(serializers.ModelSerializer):
    # 🚀 Add these lines to pull data from the related User model
    username = serializers.ReadOnlyField(source='user.username')
    fan_preferences = FanPreferenceSerializer(source='user.fan_preferences', many=True, read_only=True)
    is_following = serializers.SerializerMethodField()
    followers_count = serializers.SerializerMethodField()
    following_count = serializers.SerializerMethodField()
    user_id = serializers.ReadOnlyField(source='user.id')
    profile_image = serializers.SerializerMethodField()    
    class Meta:
        model = Profile
        # 🚀 Add 'username' and 'fan_preferences' to the fields
        fields = ['id', 'user_id', 'display_name', 'bio', 'profile_image', 'banner_image', 'fcm_token', 'username', 'fan_preferences', 'is_following', 'followers_count', 'following_count']

    def update(self, instance, validated_data):
        return super().update(instance, validated_data)

    def get_is_following(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            # Check if the logged-in user follows the owner of THIS profile
            return Follow.objects.filter(follower=request.user, followed=obj.user).exists()
        return False
    
    def get_profile_image(self, obj):
        if obj.profile_image:
            # 🚀 This forces the serializer to return the https://storage... link
            return obj.profile_image.url
        return None

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