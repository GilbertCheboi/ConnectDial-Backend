from rest_framework import generics, permissions
from .serializers import PostSerializer, CommentSerializer
from feeds.models import UserFollow, TeamFollow, LeagueFollow
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import PostLike, Post, Comment




from django.db.models import Count, Exists, OuterRef
from rest_framework import generics, permissions
from .models import Post, PostLike
from .serializers import PostSerializer

class PostListCreateView(generics.ListCreateAPIView):
    serializer_class = PostSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """
        Optimized queryset to fetch user identity (team/league) 
        and engagement counts in a single database hit.
        """
        user = self.request.user
        
        # 1. Start with select_related to 'JOIN' the User, Team, and League tables
        # This is what makes author_details.favorite_team_name work instantly.
        queryset = Post.objects.select_related(
            'author', 
            'author__favorite_team', 
            'author__favorite_league'
        ).annotate(
            # 2. Add counts for engagement metrics
            likes_count=Count('likes', distinct=True),
            comments_count=Count('comments', distinct=True),
            shares_count=Count('shares', distinct=True),
        )

        # 3. Optimization: Check if the logged-in user liked the post
        if user.is_authenticated:
            user_likes = PostLike.objects.filter(post=OuterRef('pk'), user=user)
            queryset = queryset.annotate(user_has_liked=Exists(user_likes))

        # 4. Apply filters for the Sidebar/Drawer navigation
        league_id = self.request.query_params.get('league')
        team_id = self.request.query_params.get('team')

        if league_id:
            queryset = queryset.filter(league_id=league_id)
        if team_id:
            queryset = queryset.filter(team_id=team_id)

        # 5. Always show newest posts first
        return queryset.order_by('-created_at')

    def perform_create(self, serializer):
        # Automatically set the author to the logged-in user
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

