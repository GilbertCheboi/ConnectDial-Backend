from django.urls import path, include
from .views import (
    # Auth
    CustomLoginView,
    LogoutView,
    GoogleSignInView,

    # OTP
    SendOTPView,
    VerifyOTPView,

    # Password
    ForgotPasswordView,
    ResetPasswordView,
    ChangePasswordView,

    # Email verification
    SendEmailVerificationView,
    VerifyEmailView,

    # 2FA
    Setup2FAView,
    Verify2FASetupView,
    Validate2FAView,
    Disable2FAView,
    Get2FAStatusView,

    # Token
    CheckTokenView,

    # Social
    ToggleFollowView,

    # Profile & Onboarding
    OnboardingView,
    UserProfileUpdateView,
    ProfileListView,
)

urlpatterns = [
    # ── Core auth ─────────────────────────────────────────────
    path('login/', CustomLoginView.as_view(), name='rest_login'),

    # ── Custom logout (clears FCM token) ──────────────────────
    path('logout-custom/', LogoutView.as_view(), name='logout-custom'),

    # ── Google Sign-In (JWT) ───────────────────────────────────
    path('social/google/', GoogleSignInView.as_view(), name='google_login'),

    # ── OTP ───────────────────────────────────────────────────
    path('otp/send/', SendOTPView.as_view(), name='otp-send'),
    path('otp/verify/', VerifyOTPView.as_view(), name='otp-verify'),

    # ── Password ──────────────────────────────────────────────
    path('password/forgot/', ForgotPasswordView.as_view(), name='password-forgot'),
    path('password/reset/', ResetPasswordView.as_view(), name='password-reset'),
    path('password/change/', ChangePasswordView.as_view(), name='password-change'),

    # ── Email verification ────────────────────────────────────
    path('email/send-verification/', SendEmailVerificationView.as_view(), name='email-send-verification'),
    path('email/verify/', VerifyEmailView.as_view(), name='email-verify'),

    # ── 2FA ───────────────────────────────────────────────────
    path('2fa/setup/', Setup2FAView.as_view(), name='2fa-setup'),
    path('2fa/verify-setup/', Verify2FASetupView.as_view(), name='2fa-verify-setup'),
    path('2fa/validate/', Validate2FAView.as_view(), name='2fa-validate'),
    path('2fa/disable/', Disable2FAView.as_view(), name='2fa-disable'),
    path('2fa/status/', Get2FAStatusView.as_view(), name='2fa-status'),

    # ── Token check ───────────────────────────────────────────
    path('token/check/', CheckTokenView.as_view(), name='token-check'),

    # ── Social ────────────────────────────────────────────────
    path('users/<int:user_id>/toggle-follow/', ToggleFollowView.as_view(), name='toggle-follow'),

    # ── Profile & onboarding ──────────────────────────────────
    path('onboarding/', OnboardingView.as_view(), name='onboarding'),
    path('update/', UserProfileUpdateView.as_view(), name='profile-update'),
    path('search/', ProfileListView.as_view(), name='profile-search'),

    # ── dj-rest-auth & registration (fallback — must stay last) ──
    # Kept at the bottom so dj-rest-auth's built-in password/reset/,
    # password/change/, logout/, etc. never shadow the custom views above.
    path('', include('dj_rest_auth.urls')),
    path('register/', include('dj_rest_auth.registration.urls')),
]