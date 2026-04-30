from datetime import timedelta
from django.conf import settings
from django.contrib.auth import authenticate
from django.core.mail import send_mail
from django.utils import timezone
from rest_framework import generics, filters
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import AnonRateThrottle
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import RefreshToken, AccessToken
from allauth.socialaccount.models import SocialAccount
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

from .models import (
    User, Profile, FanPreference, Follow, 
    PasswordResetOTP, TwoFactorOTP, 
    LoginHistory, AuditLog  # ← New models assumed/added
)

from .serializers import (
    UserSerializer,
    OnboardingSerializer,
    ProfileSerializer,
    CustomLoginSerializer,
)

# ==================== THROTTLES ====================

class LoginThrottle(AnonRateThrottle):
    scope = 'login'

class OTPThrottle(AnonRateThrottle):
    scope = 'otp'

class PasswordResetThrottle(AnonRateThrottle):
    scope = 'password_reset'


# ==================== HELPERS ====================

def _send_otp_email(user, otp_code, subject, purpose_label):
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


def _issue_scoped_token(user, scope: str, lifetime: timedelta) -> str:
    token = AccessToken.for_user(user)
    token.set_exp(lifetime=lifetime)
    token['scope'] = scope
    return str(token)


def _decode_scoped_token(raw_token: str, expected_scope: str):
    try:
        token = AccessToken(raw_token)
    except Exception:
        raise ValueError('Invalid or expired token.')

    if token.get('scope') != expected_scope:
        raise ValueError(f'Token scope mismatch. Expected {expected_scope}.')

    try:
        user = User.objects.get(id=token['user_id'])
    except User.DoesNotExist:
        raise ValueError('User not found.')

    return user


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


def _jwt_response(user, extra=None):
    refresh = RefreshToken.for_user(user)
    payload = {
        'access': str(refresh.access_token),
        'refresh': str(refresh),
        'user': UserSerializer(user).data,
    }
    if extra:
        payload.update(extra)
    return payload


from django.core.validators import validate_email
from django.core.exceptions import ValidationError


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
    """Centralized audit logging"""
    AuditLog.objects.create(
        user=user,
        action=action,
        ip_address=ip,
        device_info=device or "Unknown",
        extra=extra or {}
    )


def _log_login(user, request):
    """Log successful login with IP & device"""
    ip = request.META.get('HTTP_X_FORWARDED_FOR') or request.META.get('REMOTE_ADDR')
    device = request.META.get('HTTP_USER_AGENT', 'Unknown Device')

    LoginHistory.objects.create(
        user=user,
        ip_address=ip,
        device_info=device,
        success=True
    )
    _log_audit(user, 'login_success', ip, device)


# ==================== AUTH VIEWS ====================

class CustomLoginView(APIView):
    """
    Step 1: Credentials → OTP → pending_token
    """
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

    def post(self, request):
        serializer = CustomLoginSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        user = serializer.user

        # OTP Brute-force protection via model-level attempts
        otp_obj = TwoFactorOTP.generate_for(user)

        try:
            _send_otp_email(user, otp_obj.code, 'ConnectDial Login Code', 'login verification')
        except Exception:
            return Response({'error': 'Failed to send verification email.'}, status=503)

        pending_token = _issue_scoped_token(user, 'login_pending', timedelta(minutes=10))

        return Response({
            'pending_token': pending_token,
            'message': f'A verification code has been sent to {user.email}.',
        }, status=200)


class LoginVerifyOTPView(APIView):
    """
    Step 2: OTP verification → Full JWT + Login logging
    """
    permission_classes = [AllowAny]
    throttle_classes = [OTPThrottle]

    def post(self, request):
        pending_token = request.data.get('pending_token', '').strip()
        otp_code = request.data.get('otp', '').strip()

        if not pending_token or not otp_code:
            return Response({'error': 'pending_token and otp are required.'}, status=400)

        try:
            user = _decode_scoped_token(pending_token, 'login_pending')
        except ValueError as e:
            return Response({'error': str(e)}, status=401)

        otp_obj = (
            TwoFactorOTP.objects
            .filter(user=user, code=otp_code, is_used=False)
            .order_by('-created_at')
            .first()
        )

        if not otp_obj or otp_obj.is_expired():
            _log_audit(user, 'login_otp_failed', 
                      request.META.get('HTTP_X_FORWARDED_FOR') or request.META.get('REMOTE_ADDR'))
            return Response({'error': 'Invalid or expired OTP.'}, status=400)

        otp_obj.is_used = True
        otp_obj.save(update_fields=['is_used'])

        # === SUCCESS: Track login ===
        _log_login(user, request)

        return Response(_jwt_response(user), status=200)


class LoginResendOTPView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [OTPThrottle]

    def post(self, request):
        pending_token = request.data.get('pending_token', '').strip()
        if not pending_token:
            return Response({'error': 'pending_token is required.'}, status=400)

        try:
            user = _decode_scoped_token(pending_token, 'login_pending')
        except ValueError as e:
            return Response({'error': str(e)}, status=401)

        otp_obj = TwoFactorOTP.generate_for(user)
        try:
            _send_otp_email(user, otp_obj.code, 'ConnectDial Login Code', 'login verification')
        except Exception:
            return Response({'error': 'Failed to send verification email.'}, status=503)

        return Response({'message': 'Verification code resent.'}, status=200)


# ==================== GOOGLE SIGN-IN ====================

class GoogleSignInView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

    def post(self, request):
        raw_token = request.data.get('id_token', '').strip()
        if not raw_token:
            return Response({'error': 'id_token is required.'}, status=400)

        client_id = settings.SOCIALACCOUNT_PROVIDERS['google']['APP']['client_id']
        client_ids_to_try = [
            client_id,
            '849401797302-h2a3b2jhvru6fthok0rbb9b66mamhcce.apps.googleusercontent.com',
        ]

        idinfo = None
        for cid in client_ids_to_try:
            try:
                idinfo = google_id_token.verify_oauth2_token(
                    raw_token, google_requests.Request(), cid
                )
                break
            except ValueError:
                continue

        if idinfo is None:
            return Response({'error': 'Invalid Google token.'}, status=401)

        email = idinfo.get('email')
        if not email or not idinfo.get('email_verified', False):
            return Response({'error': 'Invalid or unverified Google email.'}, status=400)

        try:
            user = User.objects.get(email__iexact=email)
            created = False
        except User.DoesNotExist:
            username = _make_unique_username(email.split('@')[0])
            user = User.objects.create_user(
                username=username,
                email=email,
                auth_provider='google',
                first_name=idinfo.get('given_name', ''),
                last_name=idinfo.get('family_name', ''),
            )
            created = True
        except User.MultipleObjectsReturned:
            user = User.objects.filter(email__iexact=email).order_by('-date_joined').first()
            created = False

        SocialAccount.objects.get_or_create(user=user, provider='google', uid=idinfo['sub'])

        # Log Google login
        _log_login(user, request)

        return Response(_jwt_response(user, {'is_new_user': created}), status=200)


# ==================== FORGOT PASSWORD (Enhanced) ====================

class ForgotPasswordRequestView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetThrottle]

    def post(self, request):
        identifier = (request.data.get('identifier') or request.data.get('email', '')).strip()

        if not identifier:
            return Response({'error': 'email or username is required.'}, status=400)

        user = _get_user_by_identifier(identifier)
        if user and user.is_active:
            otp_obj = PasswordResetOTP.generate_for(user)
            try:
                _send_otp_email(user, otp_obj.code, 'ConnectDial Password Reset', 'password reset')
                _log_audit(user, 'password_reset_requested', 
                          request.META.get('HTTP_X_FORWARDED_FOR') or request.META.get('REMOTE_ADDR'))
            except Exception:
                return Response({'error': 'Failed to send reset email.'}, status=503)

        # Anti-enumeration: always return same message
        return Response({'message': 'If that account exists, a reset code has been sent.'}, status=200)


class ForgotPasswordVerifyOTPView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [OTPThrottle]

    def post(self, request):
        identifier = (request.data.get('identifier') or request.data.get('email', '')).strip()
        otp_code = request.data.get('otp', '').strip()

        if not identifier or not otp_code:
            return Response({'error': 'identifier and otp are required.'}, status=400)

        user = _get_user_by_identifier(identifier)
        if not user:
            return Response({'error': 'Invalid request.'}, status=400)

        otp_obj = (
            PasswordResetOTP.objects
            .filter(user=user, code=otp_code, is_used=False)
            .order_by('-created_at')
            .first()
        )

        if not otp_obj or otp_obj.is_expired():
            return Response({'error': 'Invalid or expired OTP.'}, status=400)

        otp_obj.is_used = True
        otp_obj.save(update_fields=['is_used'])

        reset_token = _issue_scoped_token(user, 'password_reset', timedelta(minutes=15))

        _log_audit(user, 'password_reset_otp_verified', 
                  request.META.get('HTTP_X_FORWARDED_FOR') or request.META.get('REMOTE_ADDR'))

        return Response({'reset_token': reset_token}, status=200)


class ForgotPasswordResetView(APIView):
    """
    Final step: Reset password + Auto-login (returns fresh JWT)
    """
    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetThrottle]

    def post(self, request):
        reset_token = request.data.get('reset_token', '').strip()
        new_password = request.data.get('new_password', '').strip()
        confirm_password = request.data.get('confirm_password', '').strip()

        if not reset_token or not new_password or not confirm_password:
            return Response({'error': 'reset_token, new_password, and confirm_password are required.'}, status=400)

        if new_password != confirm_password:
            return Response({'error': 'Passwords do not match.'}, status=400)

        try:
            user = _decode_scoped_token(reset_token, 'password_reset')
        except ValueError as e:
            return Response({'error': str(e)}, status=401)

        user.set_password(new_password)
        user.save(update_fields=['password'])

        _log_audit(user, 'password_reset_success', 
                  request.META.get('HTTP_X_FORWARDED_FOR') or request.META.get('REMOTE_ADDR'))

        # === UX: Auto-login after successful reset ===
        _log_login(user, request)

        return Response(_jwt_response(user), status=200)


# ==================== OTHER VIEWS ====================

class ToggleFollowView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, user_id):
        follower = request.user
        try:
            target_user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({'error': 'User not found.'}, status=404)

        if follower == target_user:
            return Response({'error': 'You cannot follow yourself.'}, status=400)

        follow_rel = Follow.objects.filter(follower=follower, followed=target_user)
        if follow_rel.exists():
            follow_rel.delete()
            return Response({'following': False, 'message': f'Unfollowed {target_user.username}'}, status=200)

        Follow.objects.create(follower=follower, followed=target_user)
        return Response({'following': True, 'message': f'Following {target_user.username}'}, status=201)


class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [AllowAny]


class OnboardingView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = OnboardingSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            user = serializer.save()
            return Response(UserSerializer(user).data, status=200)
        return Response(serializer.errors, status=400)


class ProfileListView(generics.ListAPIView):
    queryset = Profile.objects.select_related('user').all()
    serializer_class = ProfileSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    filter_backends = [filters.SearchFilter]
    search_fields = ['user__username', 'bio', 'display_name']


class UserProfileUpdateView(generics.RetrieveUpdateAPIView):
    serializer_class = ProfileSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_object(self):
        user_id = self.request.query_params.get('user_id')
        username = self.request.query_params.get('username')
        if user_id:
            user = User.objects.get(id=user_id)
        elif username:
            user = User.objects.get(username=username)
        else:
            user = self.request.user
        profile, _ = Profile.objects.get_or_create(user=user)
        return profile

    def post(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)


class LogoutView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ip = request.META.get('HTTP_X_FORWARDED_FOR') or request.META.get('REMOTE_ADDR')
        device = request.META.get('HTTP_USER_AGENT', 'Unknown')

        # Blacklist refresh token if provided
        try:
            refresh_token = request.data.get('refresh', '').strip()
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()
        except Exception:
            pass

        # Clear FCM token
        if hasattr(request.user, 'profile'):
            profile = request.user.profile
            profile.fcm_token = None
            profile.save(update_fields=['fcm_token'])

        _log_audit(request.user, 'logout', ip, device)

        return Response({'message': 'Logged out successfully.'}, status=200)