"""
admin.py – ConnectDial Posts App
──────────────────────────────────────────────────────────────────────
Key performance fixes:
  1. list_select_related = True  → tells Django admin to JOIN author +
     league in the LIST query instead of a separate SELECT per row.
  2. raw_id_fields on FKs        → the change-form never loads 10,000
     user/league/team dropdowns; uses a fast ID lookup widget instead.
  3. Custom get_queryset()        → only() fetches the columns that the
     list page actually needs — nothing more.
  4. search_fields with ^        → prefix search uses the DB index;
     without ^ Django does a LIKE '%term%' (no index).
  5. show_full_result_count=False → skips the expensive COUNT(*) that
     Django admin runs on every search.
  6. date_hierarchy caching       → list_per_page=25 limits rows/page.
"""

from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Comment,
    CommentLike,
    Hashtag,
    Post,
    PostLike,
    PostShare,
    VideoUploadSession,
)


# ─────────────────────────────────────────────────────────────────────
# INLINE: PostLike  (shown inside the Post change form)
# ─────────────────────────────────────────────────────────────────────

class PostLikeInline(admin.TabularInline):
    model          = PostLike
    extra          = 0
    max_num        = 10          # never render more than 10 rows
    raw_id_fields  = ('user',)
    readonly_fields = ('created_at',)
    can_delete     = True


# ─────────────────────────────────────────────────────────────────────
# POST ADMIN
# ─────────────────────────────────────────────────────────────────────

@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    # ── List page ─────────────────────────────────────────────────────
    list_display  = (
        'id', 'author_username', 'post_type', 'league_name',
        'video_status', 'like_count', 'comment_count',
        'is_short', 'created_at',
    )
    list_filter   = ('post_type', 'video_status', 'is_short', 'created_at')
    # ^ prefix → uses the DB index instead of LIKE '%…%'
    search_fields = ('^author__username', '^league__name', 'content')
    date_hierarchy = 'created_at'
    list_per_page  = 25                  # fewer rows = faster page render
    show_full_result_count = False       # skip the COUNT(*) on every search

    # THE critical fix: JOIN author + league in the LIST query
    list_select_related = ('author', 'league', 'team')

    # ── Change form ───────────────────────────────────────────────────
    # raw_id_fields → replaces <select> with a tiny popup widget;
    # prevents loading 10,000 users into a dropdown
    raw_id_fields   = ('author', 'league', 'team', 'parent_post')
    readonly_fields = (
        'created_at', 'updated_at',
        'like_count', 'comment_count', 'share_count', 'view_count',
    )
    filter_horizontal = ('mentions', 'hashtags')
    inlines           = [PostLikeInline]

    fieldsets = (
        ('Content', {
            'fields': ('author', 'content', 'post_type', 'media_file'),
        }),
        ('League & Team', {
            'fields': ('league', 'team'),
        }),
        ('Video', {
            'fields': ('is_short', 'video_status', 'duration'),
            'classes': ('collapse',),
        }),
        ('Social', {
            'fields': ('mentions', 'hashtags', 'parent_post', 'is_repost'),
            'classes': ('collapse',),
        }),
        ('Counters (read-only)', {
            'fields': ('like_count', 'comment_count', 'share_count', 'view_count'),
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    # ── Optimised queryset for the list page ─────────────────────────
    def get_queryset(self, request):
        """
        Only fetch the columns the list page actually renders.
        The list_select_related JOIN is preserved automatically.
        """
        return (
            super().get_queryset(request)
            .only(
                'id', 'post_type', 'video_status', 'is_short',
                'like_count', 'comment_count', 'created_at',
                # FK ids — required by list_select_related
                'author_id', 'league_id', 'team_id',
            )
        )

    # ── Custom display columns ────────────────────────────────────────
    @admin.display(description='Author', ordering='author__username')
    def author_username(self, obj):
        # obj.author is already in memory via list_select_related
        return obj.author.username

    @admin.display(description='League', ordering='league__name')
    def league_name(self, obj):
        return obj.league.name if obj.league else '—'

    @admin.display(description='Media')
    def media_preview(self, obj):
        if obj.media_file:
            return format_html(
                '<a href="{}" target="_blank">View</a>', obj.media_file.url
            )
        return '—'


# ─────────────────────────────────────────────────────────────────────
# COMMENT ADMIN
# ─────────────────────────────────────────────────────────────────────

@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display           = ('id', 'user_username', 'post_id', 'created_at')
    list_select_related    = ('user', 'post__league')
    raw_id_fields          = ('user', 'post')
    search_fields          = ('^user__username', 'content')
    show_full_result_count = False
    list_per_page          = 25

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .only('id', 'content', 'created_at', 'user_id', 'post_id')
        )

    @admin.display(description='User', ordering='user__username')
    def user_username(self, obj):
        return obj.user.username


# ─────────────────────────────────────────────────────────────────────
# HASHTAG ADMIN
# ─────────────────────────────────────────────────────────────────────

@admin.register(Hashtag)
class HashtagAdmin(admin.ModelAdmin):
    list_display           = ('id', 'name', 'created_at')
    search_fields          = ('^name',)
    show_full_result_count = False
    list_per_page          = 50


# ─────────────────────────────────────────────────────────────────────
# POST LIKE ADMIN
# ─────────────────────────────────────────────────────────────────────

@admin.register(PostLike)
class PostLikeAdmin(admin.ModelAdmin):
    list_display           = ('id', 'user_id', 'post_id', 'created_at')
    list_select_related    = ('user', 'post')
    raw_id_fields          = ('user', 'post')
    show_full_result_count = False
    list_per_page          = 50


# ─────────────────────────────────────────────────────────────────────
# POST SHARE ADMIN
# ─────────────────────────────────────────────────────────────────────

@admin.register(PostShare)
class PostShareAdmin(admin.ModelAdmin):
    list_display        = ('id', 'user_id', 'original_post_id', 'created_at')
    raw_id_fields       = ('user', 'original_post')
    list_select_related = ('user',)
    list_per_page       = 50


# ─────────────────────────────────────────────────────────────────────
# VIDEO UPLOAD SESSION ADMIN
# ─────────────────────────────────────────────────────────────────────

@admin.register(VideoUploadSession)
class VideoUploadSessionAdmin(admin.ModelAdmin):
    list_display        = ('id', 'user_id', 'post_id', 'status',
                           'uploaded_chunks', 'total_chunks', 'created_at')
    list_select_related = ('user', 'post')
    raw_id_fields       = ('user', 'post')
    readonly_fields     = ('id', 'created_at')
    list_per_page       = 25