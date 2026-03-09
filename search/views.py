from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from django.db.models import Q

from posts.models import Post
from posts.serializers import PostSerializer
from users.models import User
from leagues.models import Team, League
from rest_framework.pagination import PageNumberPagination


class SearchPagination(PageNumberPagination):
    page_size = 20


class SearchView(APIView, SearchPagination):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = request.GET.get('q', '').strip()
        if not query:
            return Response({"results": []})

        # Posts
        posts_qs = Post.objects.filter(content__icontains=query).select_related(
            'author', 'league', 'team'
        ).prefetch_related('likes', 'comments')

        # Users
        users_qs = User.objects.filter(username__icontains=query)

        # Teams
        teams_qs = Team.objects.filter(name__icontains=query)

        # Leagues
        leagues_qs = League.objects.filter(name__icontains=query)

        # Paginate posts
        results = self.paginate_queryset(posts_qs, request, view=self)
        posts_serialized = PostSerializer(results, many=True, context={'request': request}).data

        # Users
        users_data = [{"id": u.id, "username": u.username, "fan_badge": u.fan_badge} for u in users_qs]

        # Teams
        teams_data = [{"id": t.id, "name": t.name} for t in teams_qs]

        # Leagues
        leagues_data = [{"id": l.id, "name": l.name} for l in leagues_qs]

        return Response({
            "query": query,
            "posts": posts_serialized,
            "users": users_data,
            "teams": teams_data,
            "leagues": leagues_data
        })

