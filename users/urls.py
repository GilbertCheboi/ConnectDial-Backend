from django.urls import path, include

from .views import (
    # Auth
    CustomLoginView,
    RegisterView,
    OnboardingView,
    LogoutView,

    # Google
    GoogleSignInView,

    # 2FA
    TwoFAVerifyView,
    TwoFAResendView,
    TwoFAToggleView,
    TwoFAStatusView,

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
    path('login/',         CustomLoginView.as_view(),  name='rest_login'),
    path('register/',      RegisterView.as_view(),      name='register'),
    path('logout-custom/', LogoutView.as_view(),        name='logout-custom'),

    # ── Google Sign-In ────────────────────────────────────────────
    path('social/google/', GoogleSignInView.as_view(), name='google-signin'),

    # ── Two-Factor Auth ───────────────────────────────────────────
    path('2fa/verify/',  TwoFAVerifyView.as_view(),  name='2fa-verify'),
    path('2fa/resend/',  TwoFAResendView.as_view(),  name='2fa-resend'),
    path('2fa/toggle/',  TwoFAToggleView.as_view(),  name='2fa-toggle'),
    path('2fa/status/',  TwoFAStatusView.as_view(),  name='2fa-status'),

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