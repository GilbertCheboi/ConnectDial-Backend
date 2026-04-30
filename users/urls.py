from django.urls import path
from .views import (
    # Auth
    CustomLoginView,
    LoginVerifyOTPView,
    LoginResendOTPView,
    RegisterView,
    OnboardingView,
    LogoutView,
    # Google
    GoogleSignInView,
    # Forgot Password
    ForgotPasswordRequestView,
    ForgotPasswordVerifyOTPView,
    ForgotPasswordResetView,
    # Profile & Social
    UserProfileUpdateView,
    ProfileListView,
    ToggleFollowView,
)

urlpatterns = [

    # ── Core auth ────────────────────────────────────────────────
    path('login/',          CustomLoginView.as_view(),     name='login'),
    path('login/verify/',   LoginVerifyOTPView.as_view(),  name='login-verify-otp'),
    path('login/resend/',   LoginResendOTPView.as_view(),  name='login-resend-otp'),
    path('register/',       RegisterView.as_view(),        name='register'),
    path('logout-custom/',  LogoutView.as_view(),          name='logout-custom'),

    # ── Google Sign-In ────────────────────────────────────────────
    path('social/google/',  GoogleSignInView.as_view(),    name='google-signin'),

    # ── Forgot Password ───────────────────────────────────────────
    path('forgot-password/request/', ForgotPasswordRequestView.as_view(),   name='forgot-password-request'),
    path('forgot-password/verify/',  ForgotPasswordVerifyOTPView.as_view(), name='forgot-password-verify'),
    path('forgot-password/reset/',   ForgotPasswordResetView.as_view(),     name='forgot-password-reset'),

    # ── Onboarding & Profile ──────────────────────────────────────
    path('onboarding/', OnboardingView.as_view(),        name='onboarding'),
    path('update/',     UserProfileUpdateView.as_view(), name='profile-update'),
    path('search/',     ProfileListView.as_view(),       name='profile-search'),

    # ── Social ────────────────────────────────────────────────────
    path('users/<int:user_id>/toggle-follow/', ToggleFollowView.as_view(), name='toggle-follow'),
]