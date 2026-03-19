from rest_framework import serializers
from .models import User, FanPreference
from leagues.models import League, Team
from .models import Profile
# For returning existing preferences
class FanPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = FanPreference
        fields = ['league', 'team']
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
class OnboardingSerializer(serializers.Serializer):
    fan_preferences = FanPreferenceSerializer(many=True)

    def validate(self, data):
        # Ensure one team per league
        leagues = [fp['league'].id if isinstance(fp['league'], League) else fp['league']
                   for fp in data['fan_preferences']]
        if len(leagues) != len(set(leagues)):
            raise serializers.ValidationError("You can only select one team per league.")
        return data

def create(self, validated_data):
        user = self.context['request'].user
        fan_preferences_data = validated_data['fan_preferences']

        # 1. Delete old preferences
        user.fan_preferences.all().delete()

        # 2. Save new preferences to the FanPreference table
        for fp in fan_preferences_data:
            FanPreference.objects.create(
                user=user,
                league=fp['league'],
                team=fp['team']
            )

        # --- THE FIX IS HERE ---
        # 3. Update the main User model fields so PostSerializer can see them
        if fan_preferences_data:
            # We take the first preference as the "Main" identity
            primary_pref = fan_preferences_data[0]
            user.favorite_team = primary_pref['team']
            user.favorite_league = primary_pref['league']
            
            # 4. Update the fan_badge from the default string
            user.fan_badge = f"{primary_pref['team'].name} Fan"
            
            user.save() # This commits it to the users_user table

        return user

        from rest_framework import serializers

class ProfileSerializer(serializers.ModelSerializer):
    # We make these read_only=False so the frontend can update them
    class Meta:
        model = Profile
        fields = ['display_name', 'bio', 'profile_image', 'banner_image']

    def update(self, instance, validated_data):
        # This ensures images are only overwritten if new ones are provided
        return super().update(instance, validated_data)


from dj_rest_auth.serializers import LoginSerializer

class CustomLoginSerializer(LoginSerializer):
    # This is the "Delivery Man" method. 
    # It tells Django: "When the login is successful, use UserSerializer 
    # to pack the user data into the JSON response."
    def get_response_serializer(self):
        return UserSerializer