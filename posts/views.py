from rest_framework import generics, permissions
from .serializers import PostSerializer, CommentSerializer
from feeds.models import UserFollow, TeamFollow, LeagueFollow
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import PostLike, Post, Comment




class PostListCreateView(generics.ListCreateAPIView):
    serializer_class = PostSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """
        Optionally filter posts by league or team using query parameters:
        /api/posts/?league=1
        /api/posts/?league=1&team=3
        """
        queryset = Post.objects.all()
        league_id = self.request.query_params.get('league')
        team_id = self.request.query_params.get('team')

        if league_id:
            queryset = queryset.filter(league_id=league_id)
        if team_id:
            queryset = queryset.filter(team_id=team_id)
        return queryset

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)


class PostDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Post.objects.all()
    serializer_class = PostSerializer
    permission_classes = [permissions.IsAuthenticated]



class FollowingFeedView(generics.ListAPIView):
    serializer_class = PostSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user

        followed_users = UserFollow.objects.filter(
            follower=user
        ).values_list('following_id', flat=True)

        followed_teams = TeamFollow.objects.filter(
            user=user
        ).values_list('team_id', flat=True)

        followed_leagues = LeagueFollow.objects.filter(
            user=user
        ).values_list('league_id', flat=True)

        return Post.objects.filter(
            models.Q(author_id__in=followed_users) |
            models.Q(team_id__in=followed_teams) |
            models.Q(league_id__in=followed_leagues)
        ).distinct()



class LikePostView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, post_id):
        like, created = PostLike.objects.get_or_create(
            user=request.user,
            post_id=post_id
        )

        if not created:
            like.delete()
            return Response({"liked": False})

        return Response({"liked": True})




class CommentCreateView(generics.CreateAPIView):
    serializer_class = CommentSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)



class SharePostView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, post_id):
        comment = request.data.get('comment')

        PostShare.objects.create(
            user=request.user,
            original_post_id=post_id,
            comment=comment
        )

        return Response({"shared": True})

