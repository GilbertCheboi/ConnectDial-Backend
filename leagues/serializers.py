from rest_framework import serializers
from .models import League, Team

class TeamSerializer(serializers.ModelSerializer):
    class Meta:
        model = Team
        fields = ['id', 'name', 'logo', 'league']

class LeagueSerializer(serializers.ModelSerializer):
    # Optional: Include teams inside the league data if needed
    teams = TeamSerializer(many=True, read_only=True)

    class Meta:
        model = League
        fields = ['id', 'name', 'abbreviation', 'logo', 'teams']