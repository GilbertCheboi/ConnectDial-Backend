from rest_framework import generics,viewsets, permissions, status
from .serializers import PostSerializer, CommentSerializer
from feeds.models import UserFollow, TeamFollow, LeagueFollow
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import PostLike, Post, Comment

from rest_framework.decorators import action



from django.db.models import Count, Exists, OuterRef
from rest_framework import generics, permissions
from .models import Post, PostLike
from .serializers import PostSerializer

# posts/permissions.py (or wherever your permission is defined)

from rest_framework import permissions

class IsAuthorOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        # Read permissions are allowed to any request,
        # so we always allow GET, HEAD or OPTIONS requests.
        if request.method in permissions.SAFE_METHODS:
            return True

        # Check if the object has an 'author' attribute (Post) 
        # or a 'user' attribute (Comment)
        if hasattr(obj, 'author'):
            return obj.author == request.user
        
        if hasattr(obj, 'user'):
            return obj.user == request.user
            
        return False

class CommentViewSet(viewsets.ModelViewSet):
    queryset = Comment.objects.all()
    serializer_class = CommentSerializer
    permission_classes = [permissions.IsAuthenticated, IsAuthorOrReadOnly]

    def perform_create(self, serializer):
        # This handles the 'user' field automatically
        serializer.save(user=self.request.user)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response({"message": "Comment deleted"}, status=status.HTTP_204_NO_CONTENT)


class PostViewSet(viewsets.ModelViewSet):
    serializer_class = PostSerializer
    permission_class = [permissions.IsAuthenticated, IsAuthorOrReadOnly]

    def get_queryset(self):
        user = self.request.user
        
        # Optimized JOINs and Annotations
        queryset = Post.objects.select_related(
            'author', 
            'author__favorite_team', 
            'author__favorite_league'
        ).annotate(
            likes_count=Count('likes', distinct=True),
            comments_count=Count('comments', distinct=True),
            shares_count=Count('shares', distinct=True),
        )

        if user.is_authenticated:
            # Note: Ensure PostLike and OuterRef/Exists are imported
            user_likes = PostLike.objects.filter(post=OuterRef('pk'), user=user)
            queryset = queryset.annotate(user_has_liked=Exists(user_likes))

        # --- NEW FILTERING LOGIC FOR PROFILES ---
        user_id = self.request.query_params.get('user')
        filter_type = self.request.query_params.get('filter')

        if user_id:
            # This handles clicking on "Other" profiles
            queryset = queryset.filter(author_id=user_id)
        elif filter_type == 'mine' and user.is_authenticated:
            # This handles your own "My Profile" tab
            queryset = queryset.filter(author=user)
        # --- END OF PROFILE LOGIC ---

        # Existing Sidebar/Drawer filters
        league_id = self.request.query_params.get('league')
        team_id = self.request.query_params.get('team')

        if league_id:
            queryset = queryset.filter(league_id=league_id)
        if team_id:
            queryset = queryset.filter(team_id=team_id)

        return queryset.order_by('-created_at')
    def perform_create(self, serializer):
        # Automatically assign the author on creation
        serializer.save(author=self.request.user)

    def destroy(self, request, *args, **kwargs):
        """
        Custom delete response for the frontend to confirm success.
        """
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response({"message": "Post deleted successfully"}, status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def like(self, request, pk=None):
        post = self.get_object()
        user = request.user
        
        # Toggle Logic: If exists, delete it. If not, create it.
        like_queryset = PostLike.objects.filter(post=post, user=user)
        
        if like_queryset.exists():
            like_queryset.delete()
            liked = False
        else:
            PostLike.objects.create(post=post, user=user)
            liked = True
            
        # Return the new counts so the frontend can update instantly
        return Response({
            'liked': liked,
            'likes_count': post.likes.count()
        }, status=status.HTTP_200_OK)  

     
    @action(detail=True, methods=['get', 'post'])
    def comments(self, request, pk=None):
        post = self.get_object()

        if request.method == 'POST':
            serializer = CommentSerializer(data=request.data, context={'request': request})
            if serializer.is_valid():
                serializer.save(post=post, user=request.user)
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
        # For GET request, return all comments for the post
        if request.method == 'GET':
            comments = post.comments.select_related('user').annotate(
                likes_count=Count('likes', distinct=True)
            ).order_by('-created_at')
            serializer = CommentSerializer(comments, many=True, context={'request': request})
            return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def repost(self, request, pk=None):
        original_post = self.get_object()
        
        # 🚀 THE FIX: Get the league from the original post
        # Adjust 'league' to match whatever your field name is (e.g., league_id)
        original_league = getattr(original_post, 'league', None)

        repost = Post.objects.create(
            author=request.user,
            content=request.data.get('content', ''), # Optional commentary
            parent_post=original_post,
            is_repost=True,
            league=original_league  # 👈 Pass the league here to satisfy the constraint
        )
        
        return Response({'status': 'reposted', 'id': repost.id}, status=201)


class ShortVideoViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Dedicated ViewSet for the full-screen Shorts feed.
    """
    serializer_class = PostSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        
        # 1. Filter only for Shorts that actually have a video file
        queryset = Post.objects.all()

        # 2. Optimized fetching of author and league
        queryset = queryset.select_related('author', 'league')

        # 3. Annotate counts for the UI overlays
        queryset = queryset.annotate(
            likes_count=Count('likes', distinct=True),
            comments_count=Count('comments', distinct=True)
        )

        # 4. Check if the current user liked this specific short
        if user.is_authenticated:
            user_likes = PostLike.objects.filter(post=OuterRef('pk'), user=user)
            queryset = queryset.annotate(user_has_liked=Exists(user_likes))

        return queryset.order_by('-created_at')

 


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

