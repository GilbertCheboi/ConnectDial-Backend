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
  - AWS/proxy-aware IP retrieval (ALB, CloudFront, Nginx)
"""

import random
import string
import pyotp
import qrcode
import io
import base64
import hmac
import hashlib
import logging
from datetime import timedelta
import traceback
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.template.loader import render_to_string
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
from drf_spectacular.utils import extend_schema, inline_serializer, OpenApiResponse
from rest_framework import serializers as drf_serializers

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

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# REUSABLE INLINE SCHEMAS FOR extend_schema
# ─────────────────────────────────────────────

_detail_response = inline_serializer(
    name='DetailResponse',
    fields={'detail': drf_serializers.CharField()},
)

_token_schema = inline_serializer(
    name='TokenResponse',
    fields={
        'key':  drf_serializers.CharField(),
        'user': drf_serializers.DictField(),
    },
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
# IP RETRIEVAL — AWS / PROXY AWARE
# ─────────────────────────────────────────────

_TRUSTED_PROXY_COUNT = getattr(settings, "TRUSTED_PROXY_COUNT", 1)


def _get_client_ip(request) -> str:
    """
    Extract the real client IP address in a proxy/AWS-aware manner.

    Strategy:
      1. Read X-Forwarded-For header if present.
      2. Build the full IP chain (leftmost = original client).
      3. Walk right-to-left, skipping one IP per trusted proxy hop.
      4. Return the first IP that is NOT a trusted proxy.
      5. Fall back to REMOTE_ADDR if no XFF header is present.
    """
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "").strip()

    if xff:
        ip_chain = [segment.strip() for segment in xff.split(",") if segment.strip()]
        if ip_chain:
            idx = max(0, len(ip_chain) - _TRUSTED_PROXY_COUNT - 1)
            return ip_chain[idx]

    return request.META.get("REMOTE_ADDR", "")


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def generate_otp(length=6):
    """Return a numeric OTP string of the given length."""
    return "".join(random.choices(string.digits, k=length))


def send_otp_email(user, otp_code, subject, purpose_label):
    """Send HTML OTP email."""
    context = {'user': user, 'otp': otp_code}
    html_message = render_to_string('emails/password_reset_otp.html', context)
    plain_message = (
        f"Hi {user.username or user.email},\n\n"
        f"Your {purpose_label} code is: {otp_code}\n\n"
        f"This code expires in 15 minutes."
    )
    send_mail(
        subject=subject,
        message=plain_message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        html_message=html_message,
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
    signature = hmac.new(secret, payload, hashlib.sha256).hexdigest()
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
        expected_sig = hmac.new(secret, payload, hashlib.sha256).hexdigest()

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
        pass


def _log_login(user, request):
    """
    Log a successful login event with the real client IP and device info.
    Uses _get_client_ip() which is AWS ALB / CloudFront aware.
    """
    ip     = _get_client_ip(request)
    device = request.META.get("HTTP_USER_AGENT", "Unknown Device")

    try:
        LoginHistory.objects.create(
            user=user,
            ip_address=ip or None,
            device_info=device,
            success=True,
        )
    except Exception:
        pass

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


def send_welcome_email(user):
    """Send welcome email only once per user."""
    if not user or not user.email:
        logger.warning("Cannot send welcome email - user or email missing")
        return

    profile, _ = Profile.objects.get_or_create(user=user)

    if profile.welcome_email_sent:
        logger.info(f"Welcome email already sent to {user.email} - skipping")
        return

    try:
        context      = {'user': user}
        html_message = render_to_string('emails/welcome_onboarding.html', context)
        plain_message = (
            f"Hi {user.username or user.email},\n\n"
            f"Welcome to ConnectDial! 🎉\n\n"
            f"Please complete your profile to get the best experience.\n\n"
            f"Best regards,\nThe ConnectDial Team"
        )
        send_mail(
            subject='Welcome to ConnectDial! Complete Your Profile',
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        profile.welcome_email_sent = True
        profile.save(update_fields=['welcome_email_sent'])
        logger.info(f"Welcome email sent successfully to {user.email}")

    except Exception:
        logger.error(f"Failed to send welcome email to {user.email}")
        logger.error(traceback.format_exc())


# ─────────────────────────────────────────────
# EMAIL VERIFICATION
# ─────────────────────────────────────────────

@extend_schema(
    summary="Send Email Verification OTP",
    description="Send a 6-digit OTP to the authenticated user's email for verification.",
    request=None,
    responses={
        200: _detail_response,
        400: _detail_response,
    },
    tags=["Email Verification"],
)
class SendEmailVerificationView(APIView):
    """POST /auth/email/send-verification/"""
    authentication_classes = [TokenAuthentication]
    permission_classes     = [IsAuthenticated]

    def post(self, request):
        user       = request.user
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


@extend_schema(
    summary="Verify Email via OTP",
    description="Submit the OTP sent to the authenticated user's email to mark it as verified.",
    request=inline_serializer(
        name='VerifyEmailRequest',
        fields={'otp': drf_serializers.CharField()},
    ),
    responses={
        200: _detail_response,
        400: _detail_response,
    },
    tags=["Email Verification"],
)
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

@extend_schema(
    summary="Send OTP",
    description="Send a one-time password to the given email for the specified purpose (login, password_reset, email_verify).",
    request=inline_serializer(
        name='SendOTPRequest',
        fields={
            'email':   drf_serializers.EmailField(),
            'purpose': drf_serializers.CharField(default='login'),
        },
    ),
    responses={200: _detail_response},
    tags=["OTP"],
)
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


@extend_schema(
    summary="Verify OTP",
    description=(
        "Verify a one-time password. "
        "Returns a reset_token for password_reset, marks email verified for email_verify, "
        "or returns an auth token for login."
    ),
    request=inline_serializer(
        name='VerifyOTPRequest',
        fields={
            'identifier': drf_serializers.CharField(),
            'otp':        drf_serializers.CharField(),
            'purpose':    drf_serializers.CharField(default='login'),
        },
    ),
    responses={
        200: inline_serializer(
            name='VerifyOTPResponse',
            fields={
                'key':         drf_serializers.CharField(required=False),
                'reset_token': drf_serializers.CharField(required=False),
                'detail':      drf_serializers.CharField(required=False),
                'user':        drf_serializers.DictField(required=False),
            },
        ),
        400: _detail_response,
    },
    tags=["OTP"],
)
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
        ip = _get_client_ip(request)

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

@extend_schema(
    summary="Forgot Password",
    description="Send a password reset OTP to the user's email. Accepts email or username.",
    request=inline_serializer(
        name='ForgotPasswordRequest',
        fields={'email': drf_serializers.CharField()},
    ),
    responses={200: _detail_response},
    tags=["Password"],
)
class ForgotPasswordView(APIView):
    """POST /auth/password/forgot/"""
    permission_classes = [AllowAny]
    throttle_classes   = [PasswordResetThrottle]

    def post(self, request):
        identifier = request.data.get("email", "").strip()

        if not identifier:
            return Response(
                {"detail": "Email or username is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        generic_response = Response(
            {"detail": "If that account exists, a reset OTP has been sent."},
            status=status.HTTP_200_OK,
        )

        user = _get_user_by_identifier(identifier)
        if not user:
            return generic_response

        if not user.email:
            logger.error(f"User {user.username} has no email address")
            return generic_response

        otp = generate_otp()
        OTPCode.objects.filter(user=user, purpose="password_reset").delete()
        OTPCode.objects.create(
            user=user,
            code=otp,
            purpose="password_reset",
            expires_at=timezone.now() + timedelta(minutes=15),
        )

        meta = _otp_meta("password_reset")
        try:
            send_otp_email(user, otp, subject=meta['subject'], purpose_label=meta['label'])
            logger.info(f"Password reset OTP sent to {user.email}")
        except Exception:
            logger.error(f"Failed to send password reset email to {user.email}")
            logger.error(traceback.format_exc())

        return generic_response


@extend_schema(
    summary="Reset Password",
    description="Reset the user's password using a signed reset token obtained after OTP verification.",
    request=inline_serializer(
        name='ResetPasswordRequest',
        fields={
            'reset_token':  drf_serializers.CharField(),
            'new_password': drf_serializers.CharField(),
        },
    ),
    responses={
        200: _detail_response,
        400: _detail_response,
    },
    tags=["Password"],
)
class ResetPasswordView(APIView):
    """POST /auth/password/reset/"""
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

        ip = _get_client_ip(request)
        _log_audit(user, 'password_reset_completed', ip)

        return Response(
            {"detail": "Password reset successfully. Please log in again."},
            status=status.HTTP_200_OK,
        )


# ─────────────────────────────────────────────
# CHANGE PASSWORD (authenticated)
# ─────────────────────────────────────────────

@extend_schema(
    summary="Change Password",
    description="Change password for the authenticated user. Returns a new auth token.",
    request=inline_serializer(
        name='ChangePasswordRequest',
        fields={
            'old_password': drf_serializers.CharField(),
            'new_password': drf_serializers.CharField(),
        },
    ),
    responses={
        200: inline_serializer(
            name='ChangePasswordResponse',
            fields={
                'detail': drf_serializers.CharField(),
                'key':    drf_serializers.CharField(),
            },
        ),
        400: _detail_response,
    },
    tags=["Password"],
)
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
            return Response(
                {"detail": "Current password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(new_password) < 8:
            return Response(
                {"detail": "New password must be at least 8 characters."},
                status=status.HTTP_400_BAD_REQUEST,
            )

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

@extend_schema(
    summary="Setup 2FA",
    description="Generate a TOTP secret and QR code to begin 2FA enrollment.",
    request=None,
    responses={
        200: inline_serializer(
            name='Setup2FAResponse',
            fields={
                'secret':  drf_serializers.CharField(),
                'qr_code': drf_serializers.CharField(),
                'detail':  drf_serializers.CharField(),
            },
        ),
    },
    tags=["2FA"],
)
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


@extend_schema(
    summary="Verify 2FA Setup",
    description="Confirm the TOTP code from the authenticator app to activate 2FA.",
    request=inline_serializer(
        name='Verify2FASetupRequest',
        fields={'totp_code': drf_serializers.CharField()},
    ),
    responses={
        200: _detail_response,
        400: _detail_response,
    },
    tags=["2FA"],
)
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


@extend_schema(
    summary="Validate 2FA Code",
    description="Validate a TOTP code for an already-enrolled user.",
    request=inline_serializer(
        name='Validate2FARequest',
        fields={'totp_code': drf_serializers.CharField()},
    ),
    responses={
        200: _detail_response,
        400: _detail_response,
    },
    tags=["2FA"],
)
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


@extend_schema(
    summary="Disable 2FA",
    description="Disable 2FA for the authenticated user. Requires a valid TOTP code to confirm.",
    request=inline_serializer(
        name='Disable2FARequest',
        fields={'totp_code': drf_serializers.CharField()},
    ),
    responses={
        200: _detail_response,
        400: _detail_response,
    },
    tags=["2FA"],
)
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
            return Response(
                {"detail": "Invalid TOTP code. 2FA was NOT disabled."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        profile.two_fa_enabled = False
        profile.totp_secret    = None
        profile.save()
        return Response({"detail": "2FA disabled."}, status=status.HTTP_200_OK)


@extend_schema(
    summary="Get 2FA Status",
    description="Return whether 2FA and email verification are enabled for the authenticated user.",
    responses={
        200: inline_serializer(
            name='Get2FAStatusResponse',
            fields={
                'two_fa_enabled': drf_serializers.BooleanField(),
                'email_verified': drf_serializers.BooleanField(),
            },
        ),
    },
    tags=["2FA"],
)
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

@extend_schema(
    summary="Check Token Validity",
    description="Verify if the current token is valid and return user info.",
    responses={
        200: inline_serializer(
            name='CheckTokenResponse',
            fields={
                'valid': drf_serializers.BooleanField(),
                'user':  drf_serializers.DictField(),
            },
        ),
    },
    tags=["Auth"],
)
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

@extend_schema(
    summary="Google Sign In",
    description="Authenticate or register a user using a Google ID token.",
    request=inline_serializer(
        name='GoogleSignInRequest',
        fields={'id_token': drf_serializers.CharField()},
    ),
    responses={
        200: inline_serializer(
            name='GoogleSignInResponse',
            fields={
                'key':          drf_serializers.CharField(),
                'user':         drf_serializers.DictField(),
                'is_new_user':  drf_serializers.BooleanField(),
            },
        ),
        400: _detail_response,
        401: _detail_response,
    },
    tags=["Auth"],
)
class GoogleSignInView(APIView):
    """POST /auth/social/google/"""
    permission_classes = [AllowAny]
    throttle_classes   = [LoginThrottle]

    def post(self, request):
        raw_token = request.data.get('id_token', '').strip()
        if not raw_token:
            return Response({'error': 'id_token is required.'}, status=status.HTTP_400_BAD_REQUEST)

        web_client_id     = getattr(settings, 'GOOGLE_CLIENT_ID', '')
        android_client_id = getattr(settings, 'GOOGLE_ANDROID_CLIENT_ID', '')
        ios_client_id     = getattr(settings, 'GOOGLE_IOS_CLIENT_ID', '')

        valid_client_ids = [
            cid for cid in [web_client_id, android_client_id, ios_client_id] if cid
        ]

        if not valid_client_ids:
            return Response(
                {'error': 'Google Sign-In is not configured on this server.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        idinfo     = None
        last_error = None

        for cid in valid_client_ids:
            try:
                idinfo = google_id_token.verify_oauth2_token(
                    raw_token, google_requests.Request(), cid
                )
                break
            except ValueError as e:
                last_error = e
                continue

        if idinfo is None:
            return Response(
                {'error': f'Invalid Google token: {str(last_error)}'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        token_aud = idinfo.get('aud', '')
        token_azp = idinfo.get('azp', '')
        if token_aud not in valid_client_ids and token_azp not in valid_client_ids:
            return Response(
                {'error': 'Token audience does not match any registered client ID.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        email = idinfo.get('email')
        if not email or not idinfo.get('email_verified', False):
            return Response(
                {'error': 'Invalid or unverified Google email.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user    = User.objects.get(email__iexact=email)
            created = False
        except User.DoesNotExist:
            username = _make_unique_username(email.split('@')[0])
            user = User.objects.create_user(
                username=username,
                email=email,
                first_name=idinfo.get('given_name', ''),
                last_name=idinfo.get('family_name', ''),
            )
            created = True
        except User.MultipleObjectsReturned:
            user    = User.objects.filter(email__iexact=email).order_by('-date_joined').first()
            created = False

        SocialAccount.objects.get_or_create(user=user, provider='google', uid=idinfo['sub'])
        _log_login(user, request)

        if created:
            send_welcome_email(user)

        return Response(
            _token_response(user, {'is_new_user': created}),
            status=status.HTTP_200_OK,
        )


# ─────────────────────────────────────────────
# FOLLOW / UNFOLLOW
# ─────────────────────────────────────────────

@extend_schema(
    summary="Toggle Follow User",
    description="Follow a user if not already following, or unfollow if already following.",
    request=None,
    responses={
        200: inline_serializer(
            name='UnfollowResponse',
            fields={
                'following':      drf_serializers.BooleanField(),
                'message':        drf_serializers.CharField(),
                'follower_count': drf_serializers.IntegerField(),
            },
        ),
        201: inline_serializer(
            name='FollowResponse',
            fields={
                'following':      drf_serializers.BooleanField(),
                'message':        drf_serializers.CharField(),
                'follower_count': drf_serializers.IntegerField(),
            },
        ),
        400: _detail_response,
        404: _detail_response,
    },
    tags=["Users"],
)
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
            send_welcome_email(user)

        return response


@extend_schema(
    summary="User Onboarding",
    description="Set account type and fan preferences for the authenticated user.",
    request=OnboardingSerializer,
    responses={
        200: UserSerializer,
        400: _detail_response,
    },
    tags=["Auth"],
)
class OnboardingView(APIView):
    """POST /auth/onboarding/"""
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
        try:
            response = super().post(request, *args, **kwargs)

            if response.status_code == 200:
                token_key = response.data.get("key")

                if not token_key:
                    return Response(
                        {"detail": "Token not generated by auth system."},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )

                try:
                    token = Token.objects.get(key=token_key)
                except Token.DoesNotExist:
                    return Response(
                        {"detail": "Invalid token generated."},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )

                user = token.user
                response.data["user"] = UserSerializer(user).data
                _log_login(user, request)

            return response

        except Exception as e:
            return Response(
                {"detail": "Login failed", "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# ─────────────────────────────────────────────
# LOGOUT
# ─────────────────────────────────────────────

@extend_schema(
    summary="Logout",
    description="Invalidate the current auth token and clear the FCM push token.",
    request=None,
    responses={200: _detail_response},
    tags=["Auth"],
)
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


# ─────────────────────────────────────────────
# TEST VIEW — Remove before production
# ─────────────────────────────────────────────

@extend_schema(exclude=True)
class TestGoogleTokenView(APIView):
    """POST /auth/social/google/test/ — Temporary token debug view."""
    permission_classes = [AllowAny]

    def post(self, request):
        token = request.data.get('id_token')
        if not token:
            return Response({"error": "No token provided."}, status=status.HTTP_400_BAD_REQUEST)

        web_client_id     = getattr(settings, 'GOOGLE_CLIENT_ID', '')
        android_client_id = getattr(settings, 'GOOGLE_ANDROID_CLIENT_ID', '')
        ios_client_id     = getattr(settings, 'GOOGLE_IOS_CLIENT_ID', '')
        valid_client_ids  = [cid for cid in [web_client_id, android_client_id, ios_client_id] if cid]

        idinfo     = None
        last_error = None

        for cid in valid_client_ids:
            try:
                idinfo = google_id_token.verify_oauth2_token(
                    token, google_requests.Request(), cid
                )
                break
            except Exception as e:
                last_error = e
                continue

        if idinfo:
            return Response({
                "valid": True,
                "email": idinfo.get('email'),
                "name":  idinfo.get('name'),
                "aud":   idinfo.get('aud'),
                "azp":   idinfo.get('azp'),
                "sub":   idinfo.get('sub'),
            }, status=status.HTTP_200_OK)

        return Response({
            "valid":            False,
            "error":            str(last_error),
            "tried_client_ids": valid_client_ids,
        }, status=status.HTTP_400_BAD_REQUEST)


# ─────────────────────────────────────────────
# FOLLOWERS & FOLLOWING LIST VIEWS
# ─────────────────────────────────────────────

class UserFollowersListView(generics.ListAPIView):
    """GET /auth/users/<user_id>/followers/"""
    serializer_class       = ProfileSerializer
    permission_classes     = [IsAuthenticated]
    authentication_classes = [TokenAuthentication]

    def get_queryset(self):
        user_id = self.kwargs.get('user_id')
        try:
            user = User.objects.get(id=user_id)
            return Profile.objects.filter(
                user__in=user.followers.values_list('follower', flat=True)
            ).select_related('user')
        except User.DoesNotExist:
            return Profile.objects.none()


class UserFollowingListView(generics.ListAPIView):
    """GET /auth/users/<user_id>/following/"""
    serializer_class       = ProfileSerializer
    permission_classes     = [IsAuthenticated]
    authentication_classes = [TokenAuthentication]

    def get_queryset(self):
        user_id = self.kwargs.get('user_id')
        try:
            user = User.objects.get(id=user_id)
            return Profile.objects.filter(
                user__in=user.following.values_list('followed', flat=True)
            ).select_related('user')
        except User.DoesNotExist:
            return Profile.objects.none()


# ─────────────────────────────────────────────
# RESEND WELCOME EMAIL (Manual)
# ─────────────────────────────────────────────

@extend_schema(
    summary="Resend Welcome Email",
    description="Resend the welcome/onboarding email to the authenticated user.",
    request=None,
    responses={
        200: inline_serializer(
            name='ResendWelcomeEmailResponse',
            fields={
                'detail': drf_serializers.CharField(),
                'email':  drf_serializers.EmailField(),
            },
        ),
        400: _detail_response,
        500: _detail_response,
    },
    tags=["Auth"],
)
class ResendWelcomeEmailView(APIView):
    """POST /auth/welcome/resend/"""
    authentication_classes = [TokenAuthentication]
    permission_classes     = [IsAuthenticated]

    def post(self, request):
        user       = request.user
        profile, _ = Profile.objects.get_or_create(user=user)

        if not user.email:
            return Response(
                {"detail": "No email address associated with this account."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        was_sent = profile.welcome_email_sent
        profile.welcome_email_sent = False
        profile.save(update_fields=['welcome_email_sent'])

        try:
            send_welcome_email(user)
            return Response({
                "detail": "Welcome email has been resent successfully.",
                "email":  user.email,
            }, status=status.HTTP_200_OK)
        except Exception:
            profile.welcome_email_sent = was_sent
            profile.save(update_fields=['welcome_email_sent'])
            logger.error(f"Resend welcome email failed for {user.email}")
            return Response(
                {"detail": "Failed to send welcome email. Please try again later."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )