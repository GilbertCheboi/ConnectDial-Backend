from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html

from .models import (
    User, Profile, Follow, FanPreference,
    UserSession, LoginHistory, AuditLog,
    PasswordResetOTP, TwoFactorOTP
)


# ========================== USER ADMIN ==========================

class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = 'Profile'
    fk_name = 'user'
    fields = ['display_name', 'bio', 'profile_image', 'banner_image', 'fcm_token', 'is_bot']


class FanPreferenceInline(admin.TabularInline):
    model = FanPreference
    extra = 1
    fields = ['league', 'team']


class LoginHistoryInline(admin.TabularInline):
    model = LoginHistory
    extra = 0
    readonly_fields = ['timestamp', 'ip_address', 'device_info', 'success', 'otp_used']
    can_delete = False
    max_num = 10


@admin.register(User)
class CustomUserAdmin(BaseUserAdmin):
    inlines = [ProfileInline, FanPreferenceInline, LoginHistoryInline]

    list_display = [
        'username', 'email', 'account_type', 'badge_type',
        'auth_provider', 'is_active', 'is_staff', 'date_joined'
    ]
    list_filter = ['account_type', 'badge_type', 'auth_provider', 'is_active', 'is_staff', 'is_superuser']
    search_fields = ['username', 'email', 'first_name', 'last_name']
    ordering = ['-date_joined']

    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'last_name', 'email')}),
        ('ConnectDial Info', {
            'fields': (
                'account_type', 'badge_type', 'auth_provider',
                'favorite_team', 'favorite_league', 'fan_badge', 'two_fa_enabled'
            )
        }),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        ('Important Dates', {'fields': ('last_login', 'date_joined')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'password1', 'password2', 'account_type'),
        }),
    )


# ========================== PROFILE ==========================

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'display_name', 'is_bot', 'has_profile_image', 'has_banner']
    list_filter = ['is_bot']
    search_fields = ['user__username', 'user__email', 'display_name', 'bio']
    raw_id_fields = ['user']

    def has_profile_image(self, obj):
        return bool(obj.profile_image)
    has_profile_image.boolean = True
    has_profile_image.short_description = "Profile Img"

    def has_banner(self, obj):
        return bool(obj.banner_image)
    has_banner.boolean = True
    has_banner.short_description = "Banner"


# ========================== SOCIAL ==========================

@admin.register(Follow)
class FollowAdmin(admin.ModelAdmin):
    list_display = ['follower', 'followed', 'created_at']
    list_filter = ['created_at']
    search_fields = ['follower__username', 'followed__username']
    raw_id_fields = ['follower', 'followed']
    date_hierarchy = 'created_at'


@admin.register(FanPreference)
class FanPreferenceAdmin(admin.ModelAdmin):
    list_display = ['user', 'league', 'team']
    list_filter = ['league']
    search_fields = ['user__username', 'league__name']
    raw_id_fields = ['user', 'league', 'team']


# ========================== TRACKING & SECURITY ==========================

@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):
    list_display = ['user', 'ip_address', 'created_at', 'last_active']
    list_filter = ['created_at', 'last_active']
    search_fields = ['user__username', 'ip_address']
    readonly_fields = ['created_at', 'last_active']
    date_hierarchy = 'created_at'


@admin.register(LoginHistory)
class LoginHistoryAdmin(admin.ModelAdmin):
    list_display = ['user', 'success', 'timestamp', 'ip_address', 'device_info_short']
    list_filter = ['success', 'timestamp', 'otp_used']
    search_fields = ['user__username', 'ip_address']
    readonly_fields = ['timestamp']
    date_hierarchy = 'timestamp'

    def device_info_short(self, obj):
        return (obj.device_info[:60] + '...') if len(obj.device_info or '') > 60 else (obj.device_info or '')
    device_info_short.short_description = "Device"


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['action', 'user', 'ip_address', 'created_at']
    list_filter = ['action', 'created_at']
    search_fields = ['user__username', 'action', 'ip_address']
    readonly_fields = ['created_at', 'extra']
    date_hierarchy = 'created_at'


# ========================== OTP MANAGEMENT ==========================

@admin.register(PasswordResetOTP)
class PasswordResetOTPAdmin(admin.ModelAdmin):
    list_display = ['user', 'code', 'attempts', 'is_used', 'is_expired_display', 'created_at']
    list_filter = ['is_used', 'created_at']
    search_fields = ['user__username', 'code']
    readonly_fields = ['created_at']
    date_hierarchy = 'created_at'

    def is_expired_display(self, obj):
        return obj.is_expired()
    is_expired_display.boolean = True
    is_expired_display.short_description = "Expired"


@admin.register(TwoFactorOTP)
class TwoFactorOTPAdmin(admin.ModelAdmin):
    list_display = ['user', 'code', 'attempts', 'is_used', 'is_expired_display', 'created_at']
    list_filter = ['is_used', 'created_at']
    search_fields = ['user__username', 'code']
    readonly_fields = ['created_at']
    date_hierarchy = 'created_at'

    def is_expired_display(self, obj):
        return obj.is_expired()
    is_expired_display.boolean = True
    is_expired_display.short_description = "Expired"


# ========================== ADMIN SITE CUSTOMIZATION ==========================

admin.site.site_header = "ConnectDial Admin Portal"
admin.site.site_title = "ConnectDial Administration"
admin.site.index_title = "Dashboard - ConnectDial Backend"

# Optional: Custom admin actions
@admin.action(description="Mark selected users as active")
def make_active(modeladmin, request, queryset):
    queryset.update(is_active=True)

@admin.action(description="Mark selected users as inactive")
def make_inactive(modeladmin, request, queryset):
    queryset.update(is_active=False)

# Add custom actions to User admin
CustomUserAdmin.actions = [make_active, make_inactive]