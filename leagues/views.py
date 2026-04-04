from rest_framework import viewsets
from rest_framework.permissions import AllowAny
from .models import League, Team
from .serializers import LeagueSerializer, TeamSerializer

class LeagueViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = League.objects.all().order_by('id')
    serializer_class = LeagueSerializer
    
    # 🚀 THIS IS THE FIX: Disable authentication for this view
    authentication_classes = [] 
    permission_classes = [AllowAny] 
    pagination_class = None

class TeamViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TeamSerializer
    
    # 🚀 THIS IS THE FIX: Disable authentication for this view
    authentication_classes = []
    permission_classes = [AllowAny]
    pagination_class = None

    def get_queryset(self):
        queryset = Team.objects.all().order_by('name')
        league_id = self.request.query_params.get('league_id')
        if league_id:
            queryset = queryset.filter(league_id=league_id)
        return queryset