"""
views.py — Full Auth + Profile Views
======================================
Includes:
  - OTP generation & verification
  - 2FA enable/disable/verify
  - Forgot password (send OTP via email)
  - Password reset (via OTP)
  - Change password (authenticated)
  - Email verification (send + verify)
  - Logout
  - Token check
  - Toggle follow
  - Google Sign-In (DRF Token)
  - Custom Login (DRF Token)
  - Register, Onboard, Profile CRUD
  - Audit logging & login history
"""

import random
import string
import pyotp
import qrcode
import io
import base64
import hmac
import hashlib
from datetime import timedelta

from django.core.mail import send_mail
from django.core.validators import validate_email
from django.utils import timezone
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from rest_framework.exceptions import ValidationError

from rest_framework.views import APIView
from rest_framework import generics, status, filters
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.throttling import AnonRateThrottle

from dj_rest_auth.views import LoginView
from allauth.socialaccount.models import SocialAccount
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

from .models import (
    User, Profile, FanPreference, Follow,
    OTPCode, AuditLog, LoginHistory, PasswordResetOTP,
)
from .serializers import (
    UserSerializer,
    OnboardingSerializer,
    ProfileSerializer,
    CustomLoginSerializer,
)


# ─────────────────────────────────────────────
# AUTO-CREATE PROFILE ON USER CREATION
# ─────────────────────────────────────────────

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Ensure every new User gets a Profile automatically."""
    if created:
        Profile.objects.get_or_create(user=instance)


# ─────────────────────────────────────────────
# THROTTLES
# ─────────────────────────────────────────────

class LoginThrottle(AnonRateThrottle):
    scope = 'login'

class OTPThrottle(AnonRateThrottle):
    scope = 'otp'

class PasswordResetThrottle(AnonRateThrottle):
    scope = 'password_reset'


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def generate_otp(length=6):
    """Return a numeric OTP string of the given length."""
    return "".join(random.choices(string.digits, k=length))


def send_otp_email(user, otp_code, subject, purpose_label):
    """Send an OTP email to the given user."""
    send_mail(
        subject=subject,
        message=(
            f"Hi {user.username},\n\n"
            f"Your {purpose_label} code is: {otp_code}\n\n"
            f"This code expires in 5 minutes."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )


OTP_PURPOSE_META = {
    'login':          {'label': 'one-time login',     'subject': 'Your Login OTP'},
    'password_reset': {'label': 'password reset',     'subject': 'Password Reset OTP'},
    'email_verify':   {'label': 'email verification', 'subject': 'Verify Your Email'},
}

def _otp_meta(purpose: str) -> dict:
    return OTP_PURPOSE_META.get(
        purpose,
        {'label': purpose.replace('_', ' '), 'subject': f'Your {purpose.replace("_", " ").title()} OTP'},
    )


def _issue_signed_reset_token(user) -> str:
    """
    HMAC-SHA256 signed reset token.
    Format: {user_id}:{timestamp}:{hex_signature}
    Valid for 15 minutes.
    """
    timestamp = int(timezone.now().timestamp())
    payload   = f"{user.id}:{timestamp}".encode()
    secret    = settings.SECRET_KEY.encode()
    signature = hmac.new(secret, payload, digestmod=hashlib.sha256).hexdigest()  # ← fixed
    return f"{user.id}:{timestamp}:{signature}"


def _decode_signed_reset_token(raw_token: str):
    """
    Validate and decode a signed reset token.
    Returns the User instance or raises ValueError.
    """
    try:
        parts = raw_token.strip().split(":")
        if len(parts) != 3:
            raise ValueError("Malformed token.")

        user_id, timestamp, signature = parts
        payload      = f"{user_id}:{timestamp}".encode()
        secret       = settings.SECRET_KEY.encode()
        expected_sig = hmac.new(secret, payload, digestmod=hashlib.sha256).hexdigest()  # ← fixed

        if not hmac.compare_digest(expected_sig, signature):
            raise ValueError("Invalid token signature.")

        if (int(timezone.now().timestamp()) - int(timestamp)) > 900:
            raise ValueError("Reset token has expired.")

        return User.objects.get(id=int(user_id))

    except User.DoesNotExist:
        raise ValueError("User not found.")
    except (TypeError, ValueError) as e:
        raise ValueError(str(e))


def _get_user_by_identifier(identifier: str):
    identifier = identifier.strip()
    if not identifier:
        return None

    is_email = True
    try:
        validate_email(identifier)
    except ValidationError:
        is_email = False

    qs = (
        User.objects.filter(email__iexact=identifier)
        if is_email
        else User.objects.filter(username__iexact=identifier)
    )
    return qs.order_by('-date_joined').first() if qs.exists() else None


def _log_audit(user, action: str, ip: str, device: str = None, extra: dict = None):
    """Centralized audit logging — silently skips unknown action values."""
    try:
        AuditLog.objects.create(
            user=user,
            action=action,
            ip_address=ip or None,
            device_info=device or "Unknown",
            extra=extra or {},
        )
    except Exception:
        pass  # Never let audit logging crash a real request


def _log_login(user, request):
    """Log successful login with IP & device."""
    ip     = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() \
             or request.META.get("REMOTE_ADDR")
    device = request.META.get("HTTP_USER_AGENT", "Unknown Device")

    try:
        LoginHistory.objects.create(
            user=user,
            ip_address=ip or None,
            device_info=device,
            success=True,
        )
    except Exception:
        pass  # Never let login history crash a real request

    _log_audit(user, "login_success", ip, device)


def _make_unique_username(base: str) -> str:
    username = base[:150]
    if not User.objects.filter(username=username).exists():
        return username
    suffix = 1
    while True:
        candidate = f"{base[:148]}{suffix}"
        if not User.objects.filter(username=candidate).exists():
            return candidate
        suffix += 1


def _token_response(user, extra=None):
    """Build a DRF Token response payload for a user."""
    token, _ = Token.objects.get_or_create(user=user)
    payload  = {'key': token.key, 'user': UserSerializer(user).data}
    if extra:
        payload.update(extra)
    return payload


# ─────────────────────────────────────────────
# EMAIL VERIFICATION
# ─────────────────────────────────────────────

class SendEmailVerificationView(APIView):
    """POST /auth/email/send-verification/"""
    authentication_classes = [TokenAuthentication]
    permission_classes     = [IsAuthenticated]

    def post(self, request):
        user    = request.user
        profile, _ = Profile.objects.get_or_create(user=user)

        if profile.email_verified:
            return Response(
                {"detail": "Email is already verified."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        otp = generate_otp()
        OTPCode.objects.filter(user=user, purpose="email_verify").delete()
        OTPCode.objects.create(
            user=user, code=otp, purpose="email_verify",
            expires_at=timezone.now() + timedelta(minutes=10),
        )

        meta = _otp_meta("email_verify")
        send_otp_email(user, otp, subject=meta['subject'], purpose_label=meta['label'])
        return Response({"detail": "Verification OTP sent to your email."}, status=status.HTTP_200_OK)


class VerifyEmailView(APIView):
    """POST /auth/email/verify/ — Body: { "otp": "123456" }"""
    authentication_classes = [TokenAuthentication]
    permission_classes     = [IsAuthenticated]

    def post(self, request):
        otp_input = request.data.get("otp", "").strip()
        user      = request.user

        if not otp_input:
            return Response({"detail": "otp is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            record = OTPCode.objects.get(user=user, code=otp_input, purpose="email_verify")
        except OTPCode.DoesNotExist:
            return Response({"detail": "Invalid OTP."}, status=status.HTTP_400_BAD_REQUEST)

        if record.expires_at < timezone.now():
            record.delete()
            return Response({"detail": "OTP has expired."}, status=status.HTTP_400_BAD_REQUEST)

        profile, _ = Profile.objects.get_or_create(user=user)
        profile.email_verified = True
        profile.save()
        record.delete()

        return Response({"detail": "Email verified successfully."}, status=status.HTTP_200_OK)


# ─────────────────────────────────────────────
# OTP — GENERIC SEND & VERIFY
# ─────────────────────────────────────────────

class SendOTPView(APIView):
    """
    POST /auth/otp/send/
    Body: { "email": "user@example.com", "purpose": "login" }
    """
    permission_classes = [AllowAny]
    throttle_classes   = [OTPThrottle]

    def post(self, request):
        email   = request.data.get("email", "").strip().lower()
        purpose = request.data.get("purpose", "login").strip()

        if not email:
            return Response({"detail": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)

        generic_response = Response(
            {"detail": "If that email exists, an OTP has been sent."},
            status=status.HTTP_200_OK,
        )

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return generic_response

        otp = generate_otp()
        OTPCode.objects.filter(user=user, purpose=purpose).delete()
        OTPCode.objects.create(
            user=user, code=otp, purpose=purpose,
            expires_at=timezone.now() + timedelta(minutes=10),
        )

        meta = _otp_meta(purpose)
        send_otp_email(user, otp, subject=meta['subject'], purpose_label=meta['label'])
        return generic_response


class VerifyOTPView(APIView):
    """
    POST /auth/otp/verify/
    Body: { "identifier": "user@example.com", "otp": "123456", "purpose": "login" }
    """
    permission_classes = [AllowAny]
    throttle_classes   = [OTPThrottle]

    def post(self, request):
        identifier = (request.data.get('identifier') or request.data.get('email', '')).strip()
        otp_code   = request.data.get('otp', '').strip()
        purpose    = request.data.get('purpose', 'login').strip()

        if not identifier or not otp_code:
            return Response(
                {'error': 'identifier and otp are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = _get_user_by_identifier(identifier)
        if not user:
            return Response({'error': 'Invalid request.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            otp_obj = OTPCode.objects.get(user=user, code=otp_code, purpose=purpose)
        except OTPCode.DoesNotExist:
            return Response({'error': 'Invalid or expired OTP.'}, status=status.HTTP_400_BAD_REQUEST)

        if otp_obj.expires_at < timezone.now():
            otp_obj.delete()
            return Response({'error': 'OTP has expired.'}, status=status.HTTP_400_BAD_REQUEST)

        otp_obj.delete()
        ip = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() \
             or request.META.get('REMOTE_ADDR')

        if purpose == 'password_reset':
            reset_token = _issue_signed_reset_token(user)
            _log_audit(user, 'password_reset_otp_verified', ip)
            return Response({'reset_token': reset_token}, status=status.HTTP_200_OK)

        if purpose == 'email_verify':
            profile, _ = Profile.objects.get_or_create(user=user)
            profile.email_verified = True
            profile.save()
            _log_audit(user, 'email_verified_via_otp', ip)
            return Response({'detail': 'Email verified successfully.'}, status=status.HTTP_200_OK)

        # Default: login
        token, _ = Token.objects.get_or_create(user=user)
        _log_login(user, request)
        return Response(
            {'key': token.key, 'user': UserSerializer(user).data},
            status=status.HTTP_200_OK,
        )


# ─────────────────────────────────────────────
# FORGOT PASSWORD
# ─────────────────────────────────────────────

class ForgotPasswordView(APIView):
    """POST /auth/password/forgot/ — Body: { "email": "..." }"""
    permission_classes = [AllowAny]
    throttle_classes   = [PasswordResetThrottle]

    def post(self, request):
        email = request.data.get("email", "").strip().lower()

        if not email:
            return Response({"detail": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)

        generic_response = Response(
            {"detail": "If that email exists, a reset OTP has been sent."},
            status=status.HTTP_200_OK,
        )

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return generic_response

        otp = generate_otp()
        OTPCode.objects.filter(user=user, purpose="password_reset").delete()
        OTPCode.objects.create(
            user=user, code=otp, purpose="password_reset",
            expires_at=timezone.now() + timedelta(minutes=15),
        )

        meta = _otp_meta("password_reset")
        send_otp_email(user, otp, subject=meta['subject'], purpose_label=meta['label'])
        return generic_response


class ResetPasswordView(APIView):
    """POST /auth/password/reset/ — Body: { "reset_token": "...", "new_password": "..." }"""
    permission_classes = [AllowAny]

    def post(self, request):
        raw_token    = request.data.get("reset_token", "").strip()
        new_password = request.data.get("new_password", "").strip()

        if not raw_token or not new_password:
            return Response(
                {"detail": "reset_token and new_password are both required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(new_password) < 8:
            return Response(
                {"detail": "Password must be at least 8 characters."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = _decode_signed_reset_token(raw_token)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.save()
        Token.objects.filter(user=user).delete()

        ip = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() \
             or request.META.get('REMOTE_ADDR')
        _log_audit(user, 'password_reset_completed', ip)

        return Response(
            {"detail": "Password reset successfully. Please log in again."},
            status=status.HTTP_200_OK,
        )


# ─────────────────────────────────────────────
# CHANGE PASSWORD (authenticated)
# ─────────────────────────────────────────────

class ChangePasswordView(APIView):
    """POST /auth/password/change/ — Body: { "old_password": "...", "new_password": "..." }"""
    authentication_classes = [TokenAuthentication]
    permission_classes     = [IsAuthenticated]

    def post(self, request):
        old_password = request.data.get("old_password", "")
        new_password = request.data.get("new_password", "").strip()

        if not old_password or not new_password:
            return Response(
                {"detail": "old_password and new_password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not request.user.check_password(old_password):
            return Response({"detail": "Current password is incorrect."}, status=status.HTTP_400_BAD_REQUEST)

        if len(new_password) < 8:
            return Response({"detail": "New password must be at least 8 characters."}, status=status.HTTP_400_BAD_REQUEST)

        request.user.set_password(new_password)
        request.user.save()

        Token.objects.filter(user=request.user).delete()
        new_token = Token.objects.create(user=request.user)

        return Response(
            {"detail": "Password changed successfully.", "key": new_token.key},
            status=status.HTTP_200_OK,
        )


# ─────────────────────────────────────────────
# 2FA — TOTP
# ─────────────────────────────────────────────

class Setup2FAView(APIView):
    """POST /auth/2fa/setup/"""
    authentication_classes = [TokenAuthentication]
    permission_classes     = [IsAuthenticated]

    def post(self, request):
        user       = request.user
        profile, _ = Profile.objects.get_or_create(user=user)

        secret               = pyotp.random_base32()
        profile.totp_secret  = secret
        profile.two_fa_enabled = False
        profile.save()

        totp    = pyotp.TOTP(secret)
        otp_uri = totp.provisioning_uri(
            name=user.email,
            issuer_name=getattr(settings, "APP_NAME", "ConnectDial"),
        )

        img    = qrcode.make(otp_uri)
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        qr_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        return Response({
            "secret":  secret,
            "qr_code": f"data:image/png;base64,{qr_b64}",
            "detail":  "Scan the QR code, then call /auth/2fa/verify-setup/ to activate.",
        }, status=status.HTTP_200_OK)


class Verify2FASetupView(APIView):
    """POST /auth/2fa/verify-setup/ — Body: { "totp_code": "123456" }"""
    authentication_classes = [TokenAuthentication]
    permission_classes     = [IsAuthenticated]

    def post(self, request):
        totp_code  = request.data.get("totp_code", "").strip()
        profile, _ = Profile.objects.get_or_create(user=request.user)

        if not profile.totp_secret:
            return Response(
                {"detail": "No 2FA setup in progress. Call /auth/2fa/setup/ first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not pyotp.TOTP(profile.totp_secret).verify(totp_code, valid_window=1):
            return Response({"detail": "Invalid TOTP code."}, status=status.HTTP_400_BAD_REQUEST)

        profile.two_fa_enabled = True
        profile.save()
        return Response({"detail": "2FA enabled successfully."}, status=status.HTTP_200_OK)


class Validate2FAView(APIView):
    """POST /auth/2fa/validate/ — Body: { "totp_code": "123456" }"""
    authentication_classes = [TokenAuthentication]
    permission_classes     = [IsAuthenticated]

    def post(self, request):
        totp_code  = request.data.get("totp_code", "").strip()
        profile, _ = Profile.objects.get_or_create(user=request.user)

        if not profile.two_fa_enabled or not profile.totp_secret:
            return Response({"detail": "2FA is not enabled."}, status=status.HTTP_400_BAD_REQUEST)

        if not pyotp.TOTP(profile.totp_secret).verify(totp_code, valid_window=1):
            return Response({"detail": "Invalid TOTP code."}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"detail": "2FA verified. Access granted."}, status=status.HTTP_200_OK)


class Disable2FAView(APIView):
    """POST /auth/2fa/disable/ — Body: { "totp_code": "123456" }"""
    authentication_classes = [TokenAuthentication]
    permission_classes     = [IsAuthenticated]

    def post(self, request):
        totp_code  = request.data.get("totp_code", "").strip()
        profile, _ = Profile.objects.get_or_create(user=request.user)

        if not profile.two_fa_enabled:
            return Response({"detail": "2FA is not currently enabled."}, status=status.HTTP_400_BAD_REQUEST)

        if not pyotp.TOTP(profile.totp_secret).verify(totp_code, valid_window=1):
            return Response({"detail": "Invalid TOTP code. 2FA was NOT disabled."}, status=status.HTTP_400_BAD_REQUEST)

        profile.two_fa_enabled = False
        profile.totp_secret    = None
        profile.save()
        return Response({"detail": "2FA disabled."}, status=status.HTTP_200_OK)


class Get2FAStatusView(APIView):
    """GET /auth/2fa/status/"""
    authentication_classes = [TokenAuthentication]
    permission_classes     = [IsAuthenticated]

    def get(self, request):
        profile, _ = Profile.objects.get_or_create(user=request.user)
        return Response({
            "two_fa_enabled": profile.two_fa_enabled,
            "email_verified": profile.email_verified,
        }, status=status.HTTP_200_OK)


# ─────────────────────────────────────────────
# TOKEN CHECK
# ─────────────────────────────────────────────

class CheckTokenView(APIView):
    """GET /auth/token/check/"""
    authentication_classes = [TokenAuthentication]
    permission_classes     = [IsAuthenticated]

    def get(self, request):
        return Response(
            {"valid": True, "user": UserSerializer(request.user).data},
            status=status.HTTP_200_OK,
        )


# ─────────────────────────────────────────────
# GOOGLE SIGN-IN (DRF Token)
# ─────────────────────────────────────────────

class GoogleSignInView(APIView):
    """POST /auth/social/google/ — Body: { "id_token": "..." }"""
    permission_classes = [AllowAny]
    throttle_classes   = [LoginThrottle]

    def post(self, request):
        raw_token = request.data.get('id_token', '').strip()
        if not raw_token:
            return Response({'error': 'id_token is required.'}, status=status.HTTP_400_BAD_REQUEST)

        client_id = settings.SOCIALACCOUNT_PROVIDERS['google']['APP']['client_id']

        try:
            idinfo = google_id_token.verify_oauth2_token(
                raw_token, google_requests.Request(), client_id
            )
        except ValueError:
            return Response({'error': 'Invalid Google token.'}, status=status.HTTP_401_UNAUTHORIZED)

        email = idinfo.get('email')
        if not email or not idinfo.get('email_verified', False):
            return Response({'error': 'Invalid or unverified Google email.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user    = User.objects.get(email__iexact=email)
            created = False
        except User.DoesNotExist:
            username = _make_unique_username(email.split('@')[0])
            user = User.objects.create_user(
                username=username, email=email,
                first_name=idinfo.get('given_name', ''),
                last_name=idinfo.get('family_name', ''),
            )
            created = True
        except User.MultipleObjectsReturned:
            user    = User.objects.filter(email__iexact=email).order_by('-date_joined').first()
            created = False

        SocialAccount.objects.get_or_create(user=user, provider='google', uid=idinfo['sub'])
        _log_login(user, request)

        return Response(
            _token_response(user, {'is_new_user': created}),
            status=status.HTTP_200_OK,
        )


# ─────────────────────────────────────────────
# FOLLOW / UNFOLLOW
# ─────────────────────────────────────────────

class ToggleFollowView(APIView):
    """POST /auth/users/<user_id>/follow/"""
    authentication_classes = [TokenAuthentication]
    permission_classes     = [IsAuthenticated]

    def post(self, request, user_id):
        follower = request.user
        try:
            target_user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        if follower == target_user:
            return Response({"error": "You cannot follow yourself"}, status=status.HTTP_400_BAD_REQUEST)

        follow_rel = Follow.objects.filter(follower=follower, followed=target_user)

        if follow_rel.exists():
            follow_rel.delete()
            return Response({
                "following":      False,
                "message":        f"Unfollowed {target_user.username}",
                "follower_count": target_user.followers.count(),
            }, status=status.HTTP_200_OK)

        Follow.objects.create(follower=follower, followed=target_user)
        return Response({
            "following":      True,
            "message":        f"Following {target_user.username}",
            "follower_count": target_user.followers.count(),
        }, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────
# REGISTRATION & ONBOARDING
# ─────────────────────────────────────────────

class RegisterView(generics.CreateAPIView):
    queryset           = User.objects.all()
    serializer_class   = UserSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        if response.status_code == 201:
            user     = User.objects.get(id=response.data['id'])
            token, _ = Token.objects.get_or_create(user=user)
            response.data['token'] = token.key
        return response


class OnboardingView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes     = [IsAuthenticated]

    def post(self, request):
        serializer = OnboardingSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            user = serializer.save()
            return Response(UserSerializer(user).data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ─────────────────────────────────────────────
# PROFILE VIEWS
# ─────────────────────────────────────────────

class ProfileListView(generics.ListAPIView):
    queryset               = Profile.objects.select_related("user").all()
    serializer_class       = ProfileSerializer
    permission_classes     = [IsAuthenticated]
    authentication_classes = [TokenAuthentication]
    filter_backends        = [filters.SearchFilter]
    search_fields          = ["user__username", "bio", "display_name"]

    def get_queryset(self):
        return self.queryset


class UserProfileUpdateView(generics.RetrieveUpdateAPIView):
    serializer_class       = ProfileSerializer
    permission_classes     = [IsAuthenticated]
    authentication_classes = [TokenAuthentication]
    parser_classes         = [JSONParser, MultiPartParser, FormParser]

    def get_object(self):
        user_id  = self.request.query_params.get("user_id")
        username = self.request.query_params.get("username")

        if user_id:
            user       = User.objects.get(id=user_id)
            profile, _ = Profile.objects.get_or_create(user=user)
            return profile

        if username:
            user       = User.objects.get(username=username)
            profile, _ = Profile.objects.get_or_create(user=user)
            return profile

        profile, _ = Profile.objects.get_or_create(user=self.request.user)
        return profile

    def post(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        partial    = kwargs.pop("partial", True)
        instance   = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)

        if serializer.is_valid():
            self.perform_update(serializer)
            return Response(
                {"message": "Profile updated successfully", "data": serializer.data},
                status=status.HTTP_200_OK,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ─────────────────────────────────────────────
# CUSTOM LOGIN (DRF Token)
# ─────────────────────────────────────────────

class CustomLoginView(LoginView):
    serializer_class = CustomLoginSerializer

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)

        if response.status_code == 200:
            token_key             = response.data.get("key")
            token                 = Token.objects.get(key=token_key)
            user                  = token.user
            response.data["user"] = UserSerializer(user).data
            _log_login(user, request)

        return response


# ─────────────────────────────────────────────
# LOGOUT
# ─────────────────────────────────────────────

class LogoutView(APIView):
    """POST /auth/logout/"""
    authentication_classes = [TokenAuthentication]
    permission_classes     = [IsAuthenticated]

    def post(self, request):
        profile, _ = Profile.objects.get_or_create(user=request.user)
        profile.fcm_token = None
        profile.save()

        if hasattr(request.user, "auth_token"):
            request.user.auth_token.delete()

        return Response({"message": "Logged out successfully"}, status=status.HTTP_200_OK)