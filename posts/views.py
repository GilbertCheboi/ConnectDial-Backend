from rest_framework import generics,viewsets, permissions, status
from .serializers import PostSerializer, CommentSerializer
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import PostLike, Post, Comment

from rest_framework.decorators import action
from users.models import Follow


from django.db.models import Q, Count, OuterRef, Exists
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
    permission_classes = [permissions.IsAuthenticated, IsAuthorOrReadOnly]

    def get_queryset(self):
        user = self.request.user
        
        # 1. Base Queryset with Correct Optimization
        queryset = Post.objects.select_related(
            'author', 
            'parent_post',                
            'parent_post__author',        
        ).prefetch_related(
            'author__profile',
            'parent_post__author__profile',
        ).annotate(
            likes_count=Count('likes', distinct=True),
            comments_count=Count('comments', distinct=True),
            shares_count=Count('shares', distinct=True),
            reposts_count=Count('quoted_by', distinct=True),
        )

        # 2. Add "liked_by_me" logic
        if user.is_authenticated:
            user_likes = PostLike.objects.filter(post=OuterRef('pk'), user=user)
            queryset = queryset.annotate(user_has_liked=Exists(user_likes))

        # --- 3. EXTRACTION OF PARAMS ---
        user_id = self.request.query_params.get('user')
        filter_type = self.request.query_params.get('filter')
        league_id = self.request.query_params.get('league')
        leagues_list = self.request.query_params.get('leagues') 
        team_id = self.request.query_params.get('team')
        feed_type = self.request.query_params.get('feed_type') # 🚀 NEW: global vs following

        # --- 4. FILTERING LOGIC ---

        # A. Personalized Following Feed (The "Home" Feed)
        if feed_type == 'following' and user.is_authenticated:
            # Get the list of user IDs that the current user follows
            following_ids = Follow.objects.filter(follower=user).values_list('followed_id', flat=True)
            # Include user's own posts in their following feed
            queryset = queryset.filter(author_id__in=list(following_ids) + [user.id])

        # B. Profile View Logic
        elif user_id:
            queryset = queryset.filter(author_id=user_id)
        elif filter_type == 'mine' and user.is_authenticated:
            queryset = queryset.filter(author=user)

        # C. Specific League/Team (Drawer Navigation)
        elif league_id:
            queryset = queryset.filter(league_id=league_id)
        elif team_id:
            queryset = queryset.filter(team_id=team_id)

        # D. The Hard Filter (Onboarding preferences)
        elif leagues_list:
            try:
                ids = [int(x) for x in leagues_list.split(',') if x.strip().isdigit()]
                queryset = queryset.filter(league_id__in=ids)
            except ValueError:
                pass
        
        # If feed_type is 'global' or no filters match, it returns the full optimized queryset
        return queryset.order_by('-created_at')
        
        return queryset.order_by('-created_at')
    def perform_create(self, serializer):
        # 1. Get the parent_post ID from the request (sent by Quote logic)
        parent_id = self.request.data.get('parent_post')
        
        if parent_id:
            # 2. Save the post linked to the original post
            # We use parent_post_id to avoid an extra database lookup
            serializer.save(
                author=self.request.user, 
                parent_post_id=parent_id
            )
        else:
            # 3. Standard post creation
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

     
    @action(
        detail=True, 
        methods=['get', 'post'], 
        permission_classes=[permissions.IsAuthenticated] # 🚀 OVERRIDE HERE
    )
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

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def repost(self, request, pk=None):
        original_post = self.get_object()
        
        # 1. Prevent duplicate simple reposts (optional but recommended)
        existing_repost = Post.objects.filter(
            author=request.user, 
            parent_post=original_post, 
            content='' # Simple reposts have no content
        ).first()

        if existing_repost:
            # If they click it again, they might want to "Undo" the repost
            existing_repost.delete()
            return Response({
                'status': 'unreposted',
                'reposts_count': Post.objects.filter(parent_post=original_post).count()
            }, status=200)

        # 2. Create the Repost
        repost = Post.objects.create(
            author=request.user,
            content='', 
            parent_post=original_post,
            post_type='standard', # or 'repost' if you have that type
            league=original_post.league
        )
        
        # 3. Return the NEW count for the frontend to update the UI
        # We count all posts where this post is the 'parent'
        new_count = Post.objects.filter(parent_post=original_post).count()
        
        return Response({
            'status': 'reposted', 
            'id': repost.id,
            'reposts_count': new_count
        }, status=201)

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

