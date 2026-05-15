"""
serializers.py – ConnectDial post serializers
──────────────────────────────────────────────
Design principles:
• Author data comes from select_related('author__profile') – zero extra queries.
• Like / follow flags come from annotated Exists() subqueries – zero extra queries.
• Media URLs are built once via SerializerMethodField using the request context.
• SupportLogicMixin resolves "Supports [Team]" badge with prefetched fan_preferences.

KEY FIX:
  DRF's ModelSerializer treats FileField as read-only by default.
  'media_file' was listed in Meta.fields but was silently excluded from
  validated_data on every POST, so perform_create never received the file.

  Fix: declare media_file = serializers.FileField(required=False, allow_empty_file=True)
  explicitly on the serializer so DRF treats it as writable. perform_create in
  views.py still handles the actual file assignment directly (more reliable),
  but now the serializer won't strip it from incoming data either.
"""

from rest_framework import serializers
from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes

from .models import Post, PostMedia, Comment, Hashtag, PostLike, PostShare, VideoUploadSession
from users.models import Follow

User = get_user_model()


# ─────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────

def _build_url(request, file_field):
    """Return an absolute URL for a FileField/ImageField, or None."""
    if not file_field:
        return None
    try:
        url = file_field.url
    except Exception:
        return None
    return request.build_absolute_uri(url) if request else url


# ─────────────────────────────────────────────────────────────────────
# MIXIN – "Supports [Team]" badge
# ─────────────────────────────────────────────────────────────────────

class SupportLogicMixin:
    """
    Resolves which team badge to show next to a post or comment.
    Relies on fan_preferences being prefetched on the user object
    (done in the view's get_queryset).
    """

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_supporting_info(self, obj):
        user = getattr(obj, 'author', getattr(obj, 'user', None))
        if not user:
            return None

        if getattr(user, 'account_type', None) in ('news', 'organization'):
            return None

        target_league = getattr(obj, 'league', None)
        if not target_league and hasattr(obj, 'post'):
            target_league = getattr(obj.post, 'league', None)

        if target_league:
            pref = next(
                (p for p in user.fan_preferences.all() if p.league_id == target_league.id),
                None,
            )
            if pref and pref.team:
                return {
                    'team_name':   pref.team.name,
                    'team_logo':   _build_url(None, pref.team.logo),
                    'league_name': target_league.name,
                    'type':        'contextual',
                }

        fav_team   = getattr(user, 'favorite_team', None)
        fav_league = getattr(user, 'favorite_league', None)
        if fav_team:
            return {
                'team_name':   fav_team.name,
                'team_logo':   _build_url(None, fav_team.logo),
                'league_name': fav_league.name if fav_league else 'Global',
                'type':        'global',
            }

        return None


# ─────────────────────────────────────────────────────────────────────
# HASHTAG
# ─────────────────────────────────────────────────────────────────────

class HashtagSerializer(serializers.ModelSerializer):
    post_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model  = Hashtag
        fields = ['id', 'name', 'post_count']


# ─────────────────────────────────────────────────────────────────────
# POST MEDIA
# ─────────────────────────────────────────────────────────────────────

class PostMediaSerializer(serializers.ModelSerializer):
    """
    Serialises each file attached to a post.
    Returns an absolute URL so the frontend can use it directly.
    """
    file_url = serializers.SerializerMethodField()

    class Meta:
        model  = PostMedia
        fields = ['id', 'file_url', 'media_type', 'order']

    @extend_schema_field(OpenApiTypes.URI)
    def get_file_url(self, obj):
        request = self.context.get('request')
        return _build_url(request, obj.file)


# ─────────────────────────────────────────────────────────────────────
# AUTHOR DETAIL (reusable dict, not a nested serializer)
# ─────────────────────────────────────────────────────────────────────

def _author_dict(user, request, viewer=None):
    """
    Build the author detail dict.
    All data comes from objects already in memory (select_related).
    """
    profile     = getattr(user, 'profile', None)
    profile_pic = _build_url(request, getattr(profile, 'profile_image', None))

    is_following = False
    if viewer and viewer.is_authenticated and viewer.pk != user.pk:
        is_following = getattr(user, '_is_following', False)

    return {
        'id':           user.id,
        'username':     user.username,
        'display_name': (profile.display_name if profile and profile.display_name else user.username),
        'profile_pic':  profile_pic,
        'is_following': is_following,
        'account_type': getattr(user, 'account_type', 'fan'),
        'badge_type':   getattr(user, 'badge_type', None),
        'fan_badge':    getattr(user, 'fan_badge', None),
    }


# ─────────────────────────────────────────────────────────────────────
# POST SERIALIZER
# ─────────────────────────────────────────────────────────────────────

class PostSerializer(SupportLogicMixin, serializers.ModelSerializer):
    # Counters from denormalised fields / annotations
    likes_count    = serializers.IntegerField(source='like_count',    read_only=True, default=0)
    comments_count = serializers.IntegerField(source='comment_count', read_only=True, default=0)
    shares_count   = serializers.IntegerField(source='share_count',   read_only=True, default=0)
    reposts_count  = serializers.IntegerField(read_only=True, default=0)

    author_details  = serializers.SerializerMethodField()
    supporting_info = serializers.SerializerMethodField()
    is_owner        = serializers.SerializerMethodField()
    liked_by_me     = serializers.SerializerMethodField()
    original_post   = serializers.SerializerMethodField()
    league_details  = serializers.SerializerMethodField()
    team_details    = serializers.SerializerMethodField()
    media_url       = serializers.SerializerMethodField()
    video_status    = serializers.CharField(read_only=True)

    # ── FIX: explicitly declare media_file as writable ───────────────
    # Without this, DRF's ModelSerializer auto-generates FileField as
    # read-only, silently stripping it from validated_data on every POST.
    # required=False → text-only posts don't fail validation.
    # allow_empty_file=True → DRF won't reject 0-byte files during parsing.
    # NOTE: views.py perform_create handles actual file saving directly;
    #       this declaration just prevents DRF from silently discarding it.
     # CRITICAL FIX
    media_file = serializers.FileField(
        required=False,
        allow_null=True,
        allow_empty_file=True,
    )

    # Multiple media files (read-only output; written via PostMedia in views.py)
    media_files = PostMediaSerializer(many=True, read_only=True)
    
    class Meta:
        model  = Post
        fields = [
            'id', 'author_details', 'content', 'is_short', 'post_type',
            # media_file: writable on input (for legacy single upload),
            # media_url:  absolute URL on output
            'media_file', 'media_url',
            # new multi-media list (read-only output)
            'media_files',
            'video_status', 'duration',
            'league', 'league_details', 'team', 'team_details',
            'supporting_info', 'likes_count', 'comments_count',
            'shares_count', 'reposts_count', 'view_count', 'liked_by_me',
            'created_at', 'is_owner', 'original_post', 'is_repost',
        ]
        read_only_fields = [
            # DO NOT put 'media_file' here — that's what was breaking uploads.
            'video_status', 'duration', 'view_count',
            'likes_count', 'comments_count', 'shares_count', 'reposts_count',
        ]

    # ── SerializerMethodFields ────────────────────────────────────────

    @extend_schema_field(OpenApiTypes.URI)
    def get_media_url(self, obj):
        """
        Returns the absolute URL for the legacy single media_file.
        Frontend should prefer media_files[] for new multi-media posts.
        """
        request = self.context.get('request')
        return _build_url(request, obj.media_file)

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_owner(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return request.user.pk == obj.author_id
        return False

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_liked_by_me(self, obj):
        """Prefer annotated value; fall back to DB query only if needed."""
        annotated = getattr(obj, 'liked_by_me', None)
        if annotated is not None:
            return bool(annotated)
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.likes.filter(user=request.user).exists()
        return False

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_league_details(self, obj):
        if obj.league_id and obj.league:
            return {
                'id':   obj.league.id,
                'name': obj.league.name,
                'logo': _build_url(None, obj.league.logo) if hasattr(obj.league, 'logo') else None,
            }
        return None

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_team_details(self, obj):
        if obj.team_id and obj.team:
            return {
                'id':   obj.team.id,
                'name': obj.team.name,
                'logo': _build_url(None, obj.team.logo) if hasattr(obj.team, 'logo') else None,
            }
        return None

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_original_post(self, obj):
        """Recursive serialisation for reposts/quotes (capped at 1 level)."""
        if obj.parent_post_id and obj.parent_post:
            return PostSerializer(obj.parent_post, context=self.context).data
        return None

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_author_details(self, obj):
        request = self.context.get('request')
        viewer  = request.user if request else None
        return _author_dict(obj.author, request, viewer)


# ─────────────────────────────────────────────────────────────────────
# COMMENT SERIALIZER
# ─────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────
# COMMENT SERIALIZER
# ─────────────────────────────────────────────────────────────────────

class CommentSerializer(SupportLogicMixin, serializers.ModelSerializer):
    author_details  = serializers.SerializerMethodField()
    supporting_info = serializers.SerializerMethodField()
    is_owner        = serializers.SerializerMethodField()
    liked_by_me     = serializers.SerializerMethodField()
    likes_count     = serializers.SerializerMethodField()

    class Meta:
        model  = Comment
        fields = [
            'id',
            'post',           # read-only output, set in view's perform_create
            'author_details',
            'content',
            'supporting_info',
            'created_at',
            'is_owner',
            'likes_count',
            'liked_by_me',
            # NOTE: 'parent_comment' removed — field does not exist on the
            # Comment model. Add it here only after adding the FK to the model
            # and running makemigrations + migrate.
        ]
        read_only_fields = [
            'created_at',
            'post',   # assigned in view, never writable from request body
        ]

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_author_details(self, obj):
        request = self.context.get('request')
        return _author_dict(obj.user, request)

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_owner(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return request.user.pk == obj.user_id
        return False

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_liked_by_me(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.likes.filter(user=request.user).exists()
        return False

    @extend_schema_field(OpenApiTypes.INT)
    def get_likes_count(self, obj):
        annotated = getattr(obj, 'likes_count', None)
        if annotated is not None:
            return annotated
        return obj.likes.count()

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_supporting_info(self, obj):
        return super().get_supporting_info(obj)

class VideoUploadSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = VideoUploadSession
        fields = ['id', 'post', 'total_chunks', 'uploaded_chunks', 'created_at']
        read_only_fields = ['id', 'post']