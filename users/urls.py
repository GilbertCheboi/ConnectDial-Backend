from django.urls import path, include
from .views import GoogleLogin, OnboardingView, UserProfileUpdateView, CustomLoginView

urlpatterns = [
    # 1. MANUALLY OVERRIDE the login route before including the rest
    path('login/', CustomLoginView.as_view(), name='rest_login'),    
    # 2. Keep the rest of the defaults
    path('', include('dj_rest_auth.urls')),
    path('register/', include('dj_rest_auth.registration.urls')),
    
    # 3. Google Login now uses the logic that includes User data
    path('social/google/', GoogleLogin.as_view(), name='google_login'),

    # Onboarding routes
    path('onboarding/', OnboardingView.as_view(), name='onboarding'),
    path('update/', UserProfileUpdateView.as_view(), name='profile-update'),
]