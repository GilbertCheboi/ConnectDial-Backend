from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from feeds.models import TeamFollow, LeagueFollow
from leagues.models import League, Team


class OnboardingView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Expected payload:
        {
          "leagues": [1, 2],
          "teams": [5, 9]
        }
        """
        user = request.user
        leagues = request.data.get('leagues', [])
        teams = request.data.get('teams', [])

        # Follow leagues
        for league_id in leagues:
            LeagueFollow.objects.get_or_create(
                user=user,
                league_id=league_id
            )

        # Follow teams
        for team_id in teams:
            TeamFollow.objects.get_or_create(
                user=user,
                team_id=team_id
            )

        return Response(
            {"message": "Onboarding completed successfully"},
            status=status.HTTP_200_OK
        )

