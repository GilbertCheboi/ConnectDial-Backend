import random
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


# ═════════════════ USER ═════════════════
class User(AbstractUser):
    AUTH_PROVIDERS = (
        ('email', 'Email'),
        ('google', 'Google'),
        ('apple', 'Apple'),
        ('facebook', 'Facebook'),
    )
    ACCOUNT_TYPES = (
        ('fan', 'Fan'),
        ('news', 'News/Media'),
        ('organization', 'Club/Organization'),
    )
    BADGE_TYPES = (
        ('none', 'None'),
        ('pioneer', 'Pioneer Member'),
        ('superfan', 'Verified Superfan'),
        ('official', 'Official Media'),
        ('verified', 'Verified Personality'),
    )

    auth_provider = models.CharField(max_length=20, choices=AUTH_PROVIDERS, default='email')
    account_type = models.CharField(max_length=15, choices=ACCOUNT_TYPES, default='fan')
    badge_type = models.CharField(max_length=15, choices=BADGE_TYPES, default='none')

    favorite_team = models.ForeignKey(
        'leagues.Team', null=True, blank=True, on_delete=models.SET_NULL
    )
    favorite_league = models.ForeignKey(
        'leagues.League', null=True, blank=True, on_delete=models.SET_NULL
    )

    fan_badge = models.CharField(max_length=50, default='Awaiting Partnership')

    # FIX 1: Removed two_fa_enabled from User — it belongs on Profile so all
    # views that do profile.two_fa_enabled work correctly without AttributeError.

    # ─── FIX: email must be unique=True at field level so Django enforces it
    # cleanly without a separate UniqueConstraint that breaks on existing
    # duplicate dev-data rows.
    # AbstractUser sets email blank=True, unique=False by default — we override.
    email = models.EmailField(unique=True, blank=True)

    # ─── REMOVED the UniqueConstraint block that was causing the migration
    # crash. The unique=True on the field above does the same job but lets
    # Django handle the column-level constraint directly rather than
    # re-building the entire table (which is what SQLite does for constraints,
    # and what blows up when duplicate emails already exist).

    class Meta:
        # Keep the table name consistent if you had prior migrations.
        # Remove this if you never set a custom db_table.
        pass

    def __str__(self):
        return self.username


# ═════════════════ PROFILE ═════════════════
class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
    )
    display_name = models.CharField(max_length=50, blank=True)
    bio = models.TextField(max_length=500, blank=True)
    profile_image = models.ImageField(upload_to='profiles/', null=True, blank=True)
    banner_image = models.ImageField(upload_to='banners/', null=True, blank=True)
    fcm_token = models.TextField(null=True, blank=True)
    is_bot = models.BooleanField(default=False)

    # FIX 1: two_fa_enabled moved here from User so profile.two_fa_enabled
    # works correctly in all 2FA views (Setup2FAView, Verify2FASetupView,
    # Validate2FAView, Disable2FAView, Get2FAStatusView).
    totp_secret = models.CharField(max_length=64, blank=True, null=True)
    two_fa_enabled = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=False)

    def __str__(self):
        return f"Profile({self.user.username})"


# ═════════════════ FOLLOW ═════════════════
class Follow(models.Model):
    follower = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='following',
        on_delete=models.CASCADE,
    )
    followed = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='followers',
        on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('follower', 'followed')


# ═════════════════ FAN PREFERENCE ═════════════════
class FanPreference(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='fan_preferences',
    )
    league = models.ForeignKey('leagues.League', on_delete=models.CASCADE)
    team = models.ForeignKey(
        'leagues.Team', null=True, blank=True, on_delete=models.CASCADE
    )

    class Meta:
        unique_together = ('user', 'league')


# ═════════════════ DEVICE & LOGIN TRACKING ═════════════════
class UserSession(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sessions',
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_active = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} @ {self.ip_address}"


class LoginHistory(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='login_history',
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    # FIX 2: Made nullable so _log_login() never raises IntegrityError when
    # the IP cannot be determined (e.g. tests, certain proxy configurations).
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    device_info = models.TextField(blank=True)
    success = models.BooleanField(default=True)
    otp_used = models.BooleanField(default=False)

    class Meta:
        ordering = ['-timestamp']
        verbose_name_plural = 'Login History'

    def __str__(self):
        status_str = '✅ Success' if self.success else '❌ Failed'
        return f"{self.user.username} - {status_str} - {self.timestamp}"


# ═════════════════ AUDIT LOG ═════════════════
class AuditLog(models.Model):
    # FIX 3: Added 'password_reset_completed' and 'email_verified_via_otp'
    # which are logged by the updated views.py. Without these entries Django
    # full_clean() validation fails and the admin shows blank labels.
    ACTIONS = (
        ('login_success',               'Login Success'),
        ('login_otp_failed',            'Login OTP Failed'),
        ('password_reset_requested',    'Password Reset Requested'),
        ('password_reset_otp_verified', 'Password Reset OTP Verified'),
        ('password_reset_completed',    'Password Reset Completed'),
        ('email_verified_via_otp',      'Email Verified via OTP'),
        ('logout',                      'Logout'),
        ('register',                    'User Registration'),
        ('google_signin',               'Google Sign-In'),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='audit_logs',
    )
    action = models.CharField(max_length=50, choices=ACTIONS)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    device_info = models.TextField(blank=True, null=True)
    extra = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'action']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.action} - {self.user} - {self.created_at}"


# ═════════════════ OTP BASE ═════════════════
class BaseOTP(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    code = models.CharField(max_length=6)
    attempts = models.IntegerField(default=0)
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ['-created_at']

    def is_expired(self):
        expiry = getattr(settings, 'OTP_EXPIRY_SECONDS', 600)
        return (timezone.now() - self.created_at).total_seconds() > expiry

    def increment_attempt(self):
        self.attempts += 1
        self.save(update_fields=['attempts'])
        return self.attempts

    @classmethod
    def clean_old_otps(cls, user):
        expiry = getattr(settings, 'OTP_EXPIRY_SECONDS', 600)
        cutoff = timezone.now() - timedelta(seconds=expiry * 2)
        cls.objects.filter(user=user, created_at__lt=cutoff).delete()


class PasswordResetOTP(BaseOTP):
    @classmethod
    def generate_for(cls, user):
        last = cls.objects.filter(user=user).first()
        if last:
            diff = (timezone.now() - last.created_at).total_seconds()
            cooldown = getattr(settings, 'OTP_RESEND_COOLDOWN', 60)
            if diff < cooldown:
                raise ValueError("Please wait before requesting a new code.")
        cls.clean_old_otps(user)
        return cls.objects.create(
            user=user,
            code=str(random.randint(100000, 999999)),
        )

    class Meta:
        verbose_name = 'Password Reset OTP'


class TwoFactorOTP(BaseOTP):
    @classmethod
    def generate_for(cls, user):
        cls.clean_old_otps(user)
        return cls.objects.create(
            user=user,
            code=str(random.randint(100000, 999999)),
        )

    class Meta:
        verbose_name = 'Two-Factor OTP'


# ═════════════════ OTP CODE (General Purpose) ═════════════════
class OTPCode(models.Model):
    """
    General-purpose OTP store used by views.py for:
      - email_verify
      - password_reset
      - login  (passwordless)
    """
    PURPOSE_CHOICES = (
        ('email_verify', 'Email Verification'),
        ('password_reset', 'Password Reset'),
        ('login', 'Passwordless Login'),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='otp_codes',
    )
    code = models.CharField(max_length=10)
    purpose = models.CharField(max_length=50, choices=PURPOSE_CHOICES)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'OTP Code'
        indexes = [
            models.Index(fields=['user', 'purpose']),
        ]

    def is_expired(self):
        return timezone.now() > self.expires_at

    def __str__(self):
        return f"{self.user.username} | {self.purpose} | expires {self.expires_at}"