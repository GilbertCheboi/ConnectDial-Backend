import random
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


# ═══════════════════════════════════════════════════════════
# Core User Model
# ═══════════════════════════════════════════════════════════
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
        'leagues.Team', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='favorite_users'
    )
    favorite_league = models.ForeignKey(
        'leagues.League', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='favorite_users'
    )
    fan_badge = models.CharField(max_length=50, default='Awaiting Partnership')

    two_fa_enabled = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['email'], name='unique_user_email'),
        ]

    @property
    def is_pioneer(self):
        return self.badge_type == 'pioneer'

    def __str__(self):
        return f"{self.username} ({self.account_type})"


# ═══════════════════════════════════════════════════════════
# Other Models
# ═══════════════════════════════════════════════════════════
class FanPreference(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='fan_preferences'
    )
    league = models.ForeignKey(
        'leagues.League', on_delete=models.CASCADE, related_name='league_fans'
    )
    team = models.ForeignKey(
        'leagues.Team', on_delete=models.CASCADE,
        related_name='team_fans', null=True, blank=True
    )
    followed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'league')

    def __str__(self):
        return f"{self.user.username} – {self.team.name if self.team else 'No team'}"


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    display_name = models.CharField(max_length=50, blank=True)
    bio = models.TextField(max_length=500, blank=True)
    profile_image = models.ImageField(upload_to='profiles/', null=True, blank=True)
    banner_image = models.ImageField(upload_to='banners/', null=True, blank=True)
    fcm_token = models.TextField(null=True, blank=True)
    is_bot = models.BooleanField(default=False)

    def __str__(self):
        return f"Profile({self.user.username})"


class Follow(models.Model):
    follower = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='following', on_delete=models.CASCADE)
    followed = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='followers', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('follower', 'followed')
        verbose_name = 'Follow'
        verbose_name_plural = 'Follows'

    def __str__(self):
        return f"{self.follower.username} → {self.followed.username}"


# ═══════════════════════════════════════════════════════════
# OTP Models
# ═══════════════════════════════════════════════════════════
class _BaseOTP(models.Model):
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(default=timezone.now)
    is_used = models.BooleanField(default=False)
    OTP_LIFETIME_MINUTES = 10

    class Meta:
        abstract = True

    @staticmethod
    def _make_code():
        return str(random.randint(100000, 999999))

    def is_valid(self):
        expiry = self.created_at + timedelta(minutes=self.OTP_LIFETIME_MINUTES)
        return not self.is_used and timezone.now() < expiry

    def mark_used(self):
        self.is_used = True
        self.save(update_fields=['is_used'])


class PasswordResetOTP(_BaseOTP):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reset_otp'
    )
    OTP_LIFETIME_MINUTES = 10

    @classmethod
    def generate_for(cls, user):
        obj, _ = cls.objects.update_or_create(
            user=user,
            defaults={
                'code': cls._make_code(),
                'is_used': False,
                'created_at': timezone.now(),
            }
        )
        return obj


class TwoFactorOTP(_BaseOTP):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='two_fa_otp'
    )
    OTP_LIFETIME_MINUTES = 5

    @classmethod
    def generate_for(cls, user):
        obj, _ = cls.objects.update_or_create(
            user=user,
            defaults={
                'code': cls._make_code(),
                'is_used': False,
                'created_at': timezone.now(),
            }
        )
        return obj