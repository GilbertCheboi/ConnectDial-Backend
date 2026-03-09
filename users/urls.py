from django.urls import path, include
from .views import GoogleLogin, OnboardingView

urlpatterns = [
    # Auth routes
    path('login/', include('dj_rest_auth.urls')),
    path('registration/', include('dj_rest_auth.registration.urls')),
    path('social/google/', GoogleLogin.as_view(), name='google_login'),

    # Onboarding route
    path('onboarding/', OnboardingView.as_view(), name='onboarding'),
]