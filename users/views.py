from datetime import timedelta
from django.conf import settings
from django.contrib.auth import authenticate
from django.core.mail import send_mail
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

from .models import User, Profile, FanPreference, Follow, PasswordResetOTP, TwoFactorOTP
from .serializers import (
    UserSerializer,
    OnboardingSerializer,
    ProfileSerializer,
    TwoFAToggleSerializer,
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
        message=f"Hi {user.username},\n\nYour {purpose_label} code is: {otp_code}\n\nThis code expires in 5 minutes.",
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
        'access':  str(refresh.access_token),
        'refresh': str(refresh),
        'user':    UserSerializer(user).data,
    }
    if extra:
        payload.update(extra)
    return payload


def _get_user_by_identifier(identifier: str):
    identifier = identifier.strip().lower()
    if '@' in identifier:
        qs = User.objects.filter(email__iexact=identifier)
    else:
        qs = User.objects.filter(username__iexact=identifier)
    if not qs.exists():
        return None
    if qs.count() > 1:
        return qs.order_by('-date_joined').first()
    return qs.first()


# ==================== AUTH VIEWS ====================

class CustomLoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes   = [LoginThrottle]

    def post(self, request):
        identifier = (request.data.get('username') or request.data.get('email', '')).strip()
        password   = request.data.get('password', '').strip()

        if not identifier or not password:
            return Response({'error': 'username/email and password are required.'}, status=400)

        user_obj = _get_user_by_identifier(identifier)
        if not user_obj:
            return Response({'error': 'Invalid credentials.'}, status=401)

        user = authenticate(request, username=user_obj.username, password=password)
        if not user:
            return Response({'error': 'Invalid credentials.'}, status=401)

        if not user.is_active:
            return Response({'error': 'Account deactivated.'}, status=403)

        if user.two_fa_enabled:
            otp_obj = TwoFactorOTP.generate_for(user)
            try:
                _send_otp_email(user, otp_obj.code, 'ConnectDial Login Code', 'login verification')
            except Exception:
                return Response({'error': 'Failed to send OTP email.'}, status=503)

            pending_token = _issue_scoped_token(user, 'two_fa_pending', timedelta(minutes=5))
            return Response({
                'two_fa_required': True,
                'pending_token':   pending_token,
            }, status=200)

        return Response(_jwt_response(user), status=200)


class GoogleSignInView(APIView):
    permission_classes = [AllowAny]
    throttle_classes   = [LoginThrottle]

    def post(self, request):
        raw_token = request.data.get('id_token', '').strip()
        if not raw_token:
            return Response({'error': 'id_token is required.'}, status=400)

        # ✅ Try multiple client IDs — Android and Web
        # React Native sends a token signed for the Android client
        # but Django must verify against the Web client ID
        client_id = settings.SOCIALACCOUNT_PROVIDERS['google']['APP']['client_id']

        print(f"🔍 Using client_id: {client_id}")
        print(f"🔍 Token prefix: {raw_token[:50]}")

        idinfo = None

        # ✅ Try verifying against both Web and Android client IDs
        client_ids_to_try = [
            client_id,  # Web client ID from .env
            '849401797302-h2a3b2jhvru6fthok0rbb9b66mamhcce.apps.googleusercontent.com',  # Android client ID
        ]

        for cid in client_ids_to_try:
            try:
                idinfo = google_id_token.verify_oauth2_token(
                    raw_token,
                    google_requests.Request(),
                    cid,
                )
                print(f"✅ Token verified with client_id: {cid}")
                break
            except ValueError as e:
                print(f"⚠️ Failed with client_id {cid}: {e}")
                continue

        if idinfo is None:
            return Response({'error': 'Invalid Google token. Could not verify with any client ID.'}, status=401)

        email = idinfo.get('email')
        if not email or not idinfo.get('email_verified', False):
            return Response({'error': 'Invalid or unverified Google email.'}, status=400)

        print(f"✅ Google email verified: {email}")

        try:
            user    = User.objects.get(email__iexact=email)
            created = False
        except User.DoesNotExist:
            base     = email.split('@')[0]
            username = _make_unique_username(base)
            user     = User.objects.create_user(
                username=username,
                email=email,
                auth_provider='google',
                first_name=idinfo.get('given_name', ''),
                last_name=idinfo.get('family_name', ''),
            )
            created = True
        except User.MultipleObjectsReturned:
            user    = User.objects.filter(email__iexact=email).order_by('-date_joined').first()
            created = False

        SocialAccount.objects.get_or_create(user=user, provider='google', uid=idinfo['sub'])

        response_data = _jwt_response(user, {'is_new_user': created})
        print(f"✅ Returning JWT for user: {user.username}, is_new_user: {created}")
        print(f"✅ Response keys: {list(response_data.keys())}")

        return Response(response_data, status=200)


# ==================== TWO-FACTOR AUTH VIEWS ====================

class TwoFAVerifyView(APIView):
    permission_classes = [AllowAny]
    throttle_classes   = [OTPThrottle]

    def post(self, request):
        pending_token = request.data.get('pending_token', '').strip()
        otp_code      = request.data.get('otp', '').strip()

        if not pending_token or not otp_code:
            return Response({'error': 'pending_token and otp are required.'}, status=400)

        try:
            user = _decode_scoped_token(pending_token, 'two_fa_pending')
        except ValueError as e:
            return Response({'error': str(e)}, status=401)

        otp_obj = (
            TwoFactorOTP.objects
            .filter(user=user, code=otp_code, is_used=False)
            .order_by('-created_at')
            .first()
        )
        if not otp_obj or otp_obj.is_expired():
            return Response({'error': 'Invalid or expired OTP.'}, status=400)

        otp_obj.is_used = True
        otp_obj.save(update_fields=['is_used'])

        return Response(_jwt_response(user), status=200)


class TwoFAResendView(APIView):
    permission_classes = [AllowAny]
    throttle_classes   = [OTPThrottle]

    def post(self, request):
        pending_token = request.data.get('pending_token', '').strip()
        if not pending_token:
            return Response({'error': 'pending_token is required.'}, status=400)

        try:
            user = _decode_scoped_token(pending_token, 'two_fa_pending')
        except ValueError as e:
            return Response({'error': str(e)}, status=401)

        otp_obj = TwoFactorOTP.generate_for(user)
        try:
            _send_otp_email(user, otp_obj.code, 'ConnectDial Login Code', 'login verification')
        except Exception:
            return Response({'error': 'Failed to send OTP email.'}, status=503)

        return Response({'message': 'OTP resent successfully.'}, status=200)


class TwoFAToggleView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes     = [IsAuthenticated]

    def post(self, request):
        serializer = TwoFAToggleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        user.two_fa_enabled = serializer.validated_data['enable']
        user.save(update_fields=['two_fa_enabled'])
        return Response({'two_fa_enabled': user.two_fa_enabled}, status=200)


class TwoFAStatusView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes     = [IsAuthenticated]

    def get(self, request):
        return Response({'two_fa_enabled': request.user.two_fa_enabled}, status=200)


# ==================== FORGOT PASSWORD VIEWS ====================

class ForgotPasswordRequestView(APIView):
    permission_classes = [AllowAny]
    throttle_classes   = [PasswordResetThrottle]

    def post(self, request):
        identifier = request.data.get('email', '').strip()
        if not identifier:
            return Response({'error': 'email is required.'}, status=400)

        user = _get_user_by_identifier(identifier)

        if user and user.is_active:
            otp_obj = PasswordResetOTP.generate_for(user)
            try:
                _send_otp_email(user, otp_obj.code, 'ConnectDial Password Reset', 'password reset')
            except Exception:
                return Response({'error': 'Failed to send reset email.'}, status=503)

        return Response({'message': 'If that account exists, a reset code has been sent.'}, status=200)


class ForgotPasswordVerifyOTPView(APIView):
    permission_classes = [AllowAny]
    throttle_classes   = [OTPThrottle]

    def post(self, request):
        identifier = request.data.get('email', '').strip()
        otp_code   = request.data.get('otp', '').strip()

        if not identifier or not otp_code:
            return Response({'error': 'email and otp are required.'}, status=400)

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
        return Response({'reset_token': reset_token}, status=200)


class ForgotPasswordResetView(APIView):
    permission_classes = [AllowAny]
    throttle_classes   = [PasswordResetThrottle]

    def post(self, request):
        reset_token      = request.data.get('reset_token', '').strip()
        new_password     = request.data.get('new_password', '').strip()
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
        return Response({'message': 'Password reset successfully.'}, status=200)


# ==================== PROFILE & SOCIAL VIEWS ====================

class ToggleFollowView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes     = [IsAuthenticated]

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
    queryset           = User.objects.all()
    serializer_class   = UserSerializer
    permission_classes = [AllowAny]


class OnboardingView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes     = [IsAuthenticated]

    def post(self, request):
        serializer = OnboardingSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            user = serializer.save()
            return Response(UserSerializer(user).data, status=200)
        return Response(serializer.errors, status=400)


class ProfileListView(generics.ListAPIView):
    queryset               = Profile.objects.select_related('user').all()
    serializer_class       = ProfileSerializer
    permission_classes     = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    filter_backends        = [filters.SearchFilter]
    search_fields          = ['user__username', 'bio', 'display_name']


class UserProfileUpdateView(generics.RetrieveUpdateAPIView):
    serializer_class       = ProfileSerializer
    permission_classes     = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    parser_classes         = [JSONParser, MultiPartParser, FormParser]

    def get_object(self):
        user_id  = self.request.query_params.get('user_id')
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
    permission_classes     = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get('refresh', '').strip()
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()
        except Exception:
            pass

        if hasattr(request.user, 'profile'):
            profile = request.user.profile
            profile.fcm_token = None
            profile.save(update_fields=['fcm_token'])

        return Response({'message': 'Logged out successfully.'}, status=200)