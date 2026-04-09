from rest_framework import generics,viewsets, permissions, status, filters
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import Post, Comment, PostLike
from .serializers import PostSerializer, CommentSerializer
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import PostLike, Post, Comment

from rest_framework.decorators import action
from users.models import Follow, FanPreference


from django.db.models import Q, Count, OuterRef, Exists
from rest_framework import generics, permissions
from .models import Post, PostLike
from .serializers import PostSerializer


from .models import Hashtag
from .serializers import HashtagSerializer
from .services import get_trending_hashtags


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

    # 🚀 Step 1: Add the Search Backend
    # This tells DRF to look for the ?search= query parameter in the URL
    filter_backends = [filters.SearchFilter]
    
    # 🚀 Step 2: Define what fields can be searched
    # Use 'author__username' to search the name of the person who posted
    # Use 'content' for the post text
    # Use 'league__name' to search for posts by league name
    search_fields = ['content', 'author__username', 'league__name']

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
        feed_type = self.request.query_params.get('feed_type')

        # --- 4. ADDITIVE FILTERING LOGIC ---
        
        # A. DEFAULT LEAGUE FILTER FOR HOME/FEED (Filter by user's favorite leagues)
        # For authenticated users, only show posts from leagues they follow
        if user.is_authenticated:
            user_league_ids = user.fan_preferences.values_list('league_id', flat=True)
            if user_league_ids:
                queryset = queryset.filter(league_id__in=user_league_ids)
        
        # B. MANDATORY LEAGUE FILTER (The Guard) - overrides default if specified
        # This still applies during search, so searching "Goal" only shows 
        # posts from your leagues!
        if league_id:
            queryset = queryset.filter(league_id=league_id)
        elif leagues_list:
            try:
                ids = [int(x) for x in leagues_list.split(',') if x.strip().isdigit()]
                if ids:
                    queryset = queryset.filter(league_id__in=ids)
            except ValueError:
                pass

        # B. SOCIAL FILTER (The "Who")
        if feed_type == 'following' and user.is_authenticated:
            following_ids = Follow.objects.filter(follower=user).values_list('followed_id', flat=True)
            queryset = queryset.filter(Q(author_id__in=following_ids) | Q(author=user))
        
        # C. PROFILE / CONTEXT FILTERS
        if user_id:
            queryset = queryset.filter(author_id=user_id)
        elif filter_type == 'mine' and user.is_authenticated:
            queryset = queryset.filter(author=user)
        
        if team_id:
            queryset = queryset.filter(team_id=team_id)

        # 5. Final Sorting
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
        like_queryset = PostLike.objects.filter(post=post, user=user)
        
        if like_queryset.exists():
            like_queryset.delete()
            post.like_count = max(0, post.like_count - 1) # Decrement counter
            liked = False
        else:
            PostLike.objects.create(post=post, user=user)
            post.like_count += 1 # Increment counter
            liked = True
            
        post.save(update_fields=['like_count']) # Persist to DB for algorithm
        return Response({'liked': liked, 'likes_count': post.like_count})

     
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

from django.db.models import Count, Exists, OuterRef
from rest_framework import viewsets, permissions
from posts.models import Post, PostLike
from posts.serializers import PostSerializer



# posts/views.py
from .services import get_personalized_shorts

class ShortVideoViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PostSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        
        # 1. Basic filtering for video content
        queryset = Post.objects.filter(is_short=True).filter(
            Q(media_file__icontains='.mp4') | 
            Q(content__icontains='youtube.com') | 
            Q(content__icontains='youtu.be')
        )

        # 2. League filtering
        followed_league_ids = user.fan_preferences.values_list('league_id', flat=True)
        if followed_league_ids.exists():
            queryset = queryset.filter(league_id__in=followed_league_ids)

        # 3. Optimization
        queryset = queryset.select_related('author', 'league', 'team').prefetch_related('hashtags')

        # 4. Inject the Algorithm Math 🚀
        # This function handles the .order_by('-hot_score') for you!
        queryset = get_personalized_shorts(queryset)

        # 5. User-specific "Liked" context
        user_likes = PostLike.objects.filter(post=OuterRef('pk'), user=user)
        
        # ✅ REMOVED the .order_by('-created_at') here to keep the Hot Score ranking
        return queryset.annotate(user_has_liked=Exists(user_likes))


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






class HashtagViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Hashtag.objects.all()
    serializer_class = HashtagSerializer

    @action(detail=False, methods=['get'])
    def trending(self, request):
        # Get top 10 tags from the last 24 hours
        trending_tags = get_trending_hashtags(limit=10, days=1)
        serializer = self.get_serializer(trending_tags, many=True)
        return Response(serializer.data)


from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import Post, VideoEngagement

class RecordEngagementView(APIView):
    """
    Endpoint called by React Native when a user finishes watching a video
    or swipes away.
    """
    def post(self, request):
        post_id = request.data.get('post_id')
        watch_time = request.data.get('watch_time') # In seconds
        completed = request.data.get('completed', False)
        
        try:
            post = Post.objects.get(id=post_id)
            
            # 1. Create the engagement record for the algorithm
            VideoEngagement.objects.create(
                user=request.user if request.user.is_authenticated else None,
                post=post,
                watch_time=watch_time,
                is_completed=completed,
                league_id=post.league.id # Helping the 'Interest Link'
            )
            
            # 2. Update the main counter on the Post for the Hot Score
            post.view_count += 1
            post.save(update_fields=['view_count'])
            
            return Response({"status": "success"}, status=status.HTTP_201_CREATED)
        except Post.DoesNotExist:
            return Response({"error": "Post not found"}, status=status.HTTP_404_NOT_FOUND)