from rest_framework import serializers
from .models import User, FanPreference
from leagues.models import League, Team

# For returning existing preferences
class FanPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = FanPreference
        fields = ['league', 'team']

class UserSerializer(serializers.ModelSerializer):
    fan_preferences = FanPreferenceSerializer(many=True, read_only=True)

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'email',
            'auth_provider',
            'fan_badge',
            'fan_preferences'
        ]


# Serializer for onboarding POST
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

        # Delete old preferences if any
        user.fan_preferences.all().delete()

        # Save new preferences
        for fp in fan_preferences_data:
            FanPreference.objects.create(
                user=user,
                league=fp['league'],
                team=fp['team']
            )
        return user