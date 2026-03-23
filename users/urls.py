from django.urls import path, include
from .views import (
    GoogleLogin, OnboardingView, UserProfileUpdateView, 
    CustomLoginView, ToggleFollowView, LogoutView # 🚀 Add LogoutView here
)

urlpatterns = [
    path('login/', CustomLoginView.as_view(), name='rest_login'),    
    path('', include('dj_rest_auth.urls')),
    path('register/', include('dj_rest_auth.registration.urls')),
    
    path('social/google/', GoogleLogin.as_view(), name='google_login'),
    path('users/<int:user_id>/toggle-follow/', ToggleFollowView.as_view(), name='toggle-follow'),

    # Onboarding and Profile
    path('onboarding/', OnboardingView.as_view(), name='onboarding'),
    # 🚀 This 'update/' route is your "View Level" entrance for the FCM token
    path('update/', UserProfileUpdateView.as_view(), name='profile-update'),
    
    # 🚀 Add this for a clean logout
    path('logout-custom/', LogoutView.as_view(), name='logout-custom'),
]