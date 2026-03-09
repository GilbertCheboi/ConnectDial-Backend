from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from .utils import get_trending_posts
from .serializers import TrendingPostSerializer

class TrendingPostsView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TrendingPostSerializer

    def get_queryset(self):
        limit = int(self.request.query_params.get('limit', 20))
        hours = int(self.request.query_params.get('hours', 48))
        return get_trending_posts(limit=limit, hours=hours)

