from rest_framework.views import APIView
from rest_framework import generics, permissions, status, filters
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from dj_rest_auth.registration.views import SocialLoginView
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from .serializers import UserSerializer, OnboardingSerializer,ProfileSerializer 
from .models import User, Profile, FanPreference
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.authentication import TokenAuthentication # <--- Add this import

from .models import Follow # Make sure to import your new model

class ToggleFollowView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, user_id):
        """
        user_id is the ID of the person the logged-in user wants to follow/unfollow.
        """
        follower = request.user
        try:
            target_user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        if follower == target_user:
            return Response({"error": "You cannot follow yourself"}, status=status.HTTP_400_BAD_REQUEST)

        # Check if the relationship already exists
        follow_rel = Follow.objects.filter(follower=follower, followed=target_user)

        if follow_rel.exists():
            # UNFOLLOW logic
            follow_rel.delete()
            return Response({
                "following": False,
                "message": f"Unfollowed {target_user.username}",
                "follower_count": target_user.followers.count()
            }, status=status.HTTP_200_OK)
        else:
            # FOLLOW logic
            Follow.objects.create(follower=follower, followed=target_user)
            return Response({
                "following": True,
                "message": f"Following {target_user.username}",
                "follower_count": target_user.followers.count()
            }, status=status.HTTP_201_CREATED)
# Social login
class GoogleLogin(SocialLoginView):
    adapter_class = GoogleOAuth2Adapter

# User registration
class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.AllowAny]

class OnboardingView(APIView):
    # This line is the "handshake" that matches your React Native 'api.js'
    authentication_classes = [TokenAuthentication] 
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        preferences_data = request.data.get('fan_preferences', [])
        append_mode = request.data.get('append_mode', False)

        # 🚀 THE FIX: Only delete if NOT appending
        if not append_mode:
            # Clear existing follows for a fresh start (Onboarding mode)
            FanPreference.objects.filter(user=user).delete()
        
        # Add/Update the new selections
        for item in preferences_data:
            FanPreference.objects.update_or_create(
                user=user,
                league_id=item['league'],
                defaults={'team_id': item['team']}
            )

        return Response({"status": "success"}, status=201)


class ProfileListView(generics.ListAPIView):
    """
    Handles the search functionality.
    Returns a list of profiles based on a ?search= query.
    """
    # Use select_related to join the User table for faster 'user__username' searching
    queryset = Profile.objects.select_related('user').all()
    serializer_class = ProfileSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [TokenAuthentication]
    
    # 🚀 Step 1: Keep the Search Filter
    filter_backends = [filters.SearchFilter]
    
    # 🚀 Step 2: Ensure these fields match your model exactly
    # We use 'user__username' because 'username' is on the AUTH_USER_MODEL, not Profile.
    search_fields = ['user__username', 'bio', 'display_name']

    def get_queryset(self):
        # 🚀 THE CHANGE: Return all profiles without excluding yourself.
        # This way, if you search your own name, you actually show up.
        return self.queryset

class UserProfileUpdateView(generics.RetrieveUpdateAPIView):
    """
    View to handle retrieving and updating the User Profile.
    Supports GET (retrieve), PUT/PATCH (update), and POST (mapped to update).
    """
    serializer_class = ProfileSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [TokenAuthentication]
    # MultiPartParser is critical for handling Image/File uploads from React Native
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    def get_object(self):
        # This is the "secret sauce" for viewing other profiles
        user_id = self.request.query_params.get('user_id')
        
        if user_id:
            # If the frontend sent ?user_id=X, find that profile
            profile, created = Profile.objects.get_or_create(user_id=user_id)
            return profile
        
        # Otherwise, return the logged-in user's profile
        profile, created = Profile.objects.get_or_create(user=self.request.user)
        return profile

    def post(self, request, *args, **kwargs):
        """
        React Native's FormData often defaults to POST. 
        We map POST to the update (PATCH) logic to avoid '405 Method Not Allowed'.
        """
        return self.update(request, *args, **kwargs)

    
    def get_object(self):
        # 🚀 Look for 'user_id' in the URL params: /api/profile/?user_id=5
        user_id = self.request.query_params.get('user_id')
        print(f"DEBUG: Requesting Profile for user_id: {user_id}") # 👈 Check your terminal
        
        if user_id:
            try:
                return Profile.objects.get(user_id=user_id)
            except Profile.DoesNotExist:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                user = User.objects.get(id=user_id)
                return Profile.objects.create(user=user)

        return Profile.objects.get(user=self.request.user)
            # Fetch the profile belonging to that specific User ID
  
        # If no user_id is provided, default to the logged-in user
        profile, created = Profile.objects.get_or_create(user=self.request.user)
        return profile

        
    def update(self, request, *args, **kwargs):
        """
        Handles the actual update logic. 
        Setting partial=True allows the frontend to send only 
        the fields that changed (e.g., just the bio).
        """
        partial = kwargs.pop('partial', True)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        
        if serializer.is_valid():
            self.perform_update(serializer)
            return Response(
                {
                    "message": "Profile updated successfully",
                    "data": serializer.data
                }, 
                status=status.HTTP_200_OK
            )
            
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


from dj_rest_auth.views import LoginView
from .serializers import CustomLoginSerializer, UserSerializer
from rest_framework.authtoken.models import Token # Import this!

class CustomLoginView(LoginView):
    serializer_class = CustomLoginSerializer

    def post(self, request, *args, **kwargs):
        # 1. Let the standard login happen (creates the token)
        response = super().post(request, *args, **kwargs)
        
        # 2. If login was successful, the response data has the 'key'
        if response.status_code == 200:
            token_key = response.data.get('key')
            token = Token.objects.get(key=token_key)
            user = token.user  # This is our actual user object
            
            # 3. Manually serialize the user and add it to the response
            user_serializer = UserSerializer(user)
            response.data['user'] = user_serializer.data
            
            # 4. Debug print to confirm it's fixed in the terminal
            print("--- 🚀 DATA INJECTED SUCCESSFULLY ---")
            print(f"Final Data: {response.data}")
            
        return response
# FIX 2: This forces Google Login to also return the User Data
class GoogleLogin(SocialLoginView):
    adapter_class = GoogleOAuth2Adapter
    
    # This is the "Secret Sauce" - it tells Google login to use 
    # the same response format as your custom login
    def get_response_serializer(self):
        return CustomLoginSerializer

# ... Keep your OnboardingView and UserProfileUpdateView as they are ...


from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # 1. Find the user's profile
        profile = request.user.profile
        
        # 2. Wipe the token so Celery doesn't try to send pushes anymore
        profile.fcm_token = None
        profile.save()

        # 3. (Optional) Delete the actual DRF Token if you use them
        if hasattr(request.user, 'auth_token'):
            request.user.auth_token.delete()

        return Response({"message": "Logged out successfully"}, status=status.HTTP_200_OK)