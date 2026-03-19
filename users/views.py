from rest_framework.views import APIView
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from dj_rest_auth.registration.views import SocialLoginView
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from .serializers import UserSerializer, OnboardingSerializer,ProfileSerializer 
from .models import User, Profile
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.authentication import TokenAuthentication # <--- Add this import


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
        serializer = OnboardingSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"message": "Onboarding complete!"})


class UserProfileUpdateView(generics.RetrieveUpdateAPIView):
    """
    View to handle retrieving and updating the User Profile.
    Supports GET (retrieve), PUT/PATCH (update), and POST (mapped to update).
    """
    serializer_class = ProfileSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [TokenAuthentication]
    # MultiPartParser is critical for handling Image/File uploads from React Native
    parser_classes = [MultiPartParser, FormParser]

    def get_object(self):
        """
        Retrieves the profile for the currently authenticated user.
        Uses get_or_create to ensure a profile exists even if signals failed.
        """
        profile, created = Profile.objects.get_or_create(user=self.request.user)
        return profile

    def post(self, request, *args, **kwargs):
        """
        React Native's FormData often defaults to POST. 
        We map POST to the update (PATCH) logic to avoid '405 Method Not Allowed'.
        """
        return self.update(request, *args, **kwargs)

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