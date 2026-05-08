"""
ConnectDial — Short Video Feed Algorithm
========================================

Scoring formula (per video):
  score =
      watch_ratio    * 4.0   (completion rate — strongest quality signal)
    + likes_count    * 2.0
    + comments_count * 3.0   (higher than likes — active engagement)
    + shares_count   * 5.0   (highest — implies real external value)
    - age_penalty           (recency decay: 0.3 per hour, capped at 24 h)
    + interest_boost        (explicit follows: league +2, team +3)
    + history_boost         (implicit from watch history: league +1, team +1.5)

Duration range:
  Shorts can be anywhere from a few seconds up to 7 200 s (2 hrs).
  The watch_ratio normalises completion rate across all lengths, so a
  90-second clip watched to completion scores the same watch_ratio as a
  2-hr match highlight watched to completion.

Caching:
  - Feed IDs cached in Redis for 5 minutes per user (CACHE_TTL).
  - Cache busted on new video creation (via signal in signals.py).
  - bypass_cache=True forces a fresh query (useful for testing / admin).

Feed source:
  - All videos come from the ShortVideo table, filtered/ranked by the
    personalised score.  No YouTube links — every video is stored and
    served from our own storage (local FileSystemStorage in dev, S3 in
    production via streaming.py).
"""

from django.db.models import (
    Avg, F, ExpressionWrapper, FloatField,
    Case, When, Value, IntegerField,
)
from django.db.models.functions import Coalesce, Extract
from django.utils import timezone
from django.core.cache import cache

from .models import ShortVideo


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

CACHE_TTL          = 60 * 5        # seconds — 5 minutes
HISTORY_LIMIT      = 10            # how many recent watched leagues/teams to consider
AGE_DECAY_PER_HOUR = 0.3           # score penalty per hour of age
AGE_DECAY_CAP_HRS  = 24.0          # decay stops after this many hours (prevents burial of older gems)

# Personalisation weights
W_WATCH_RATIO  = 4.0
W_LIKES        = 2.0
W_COMMENTS     = 3.0
W_SHARES       = 5.0

W_EXP_LEAGUE   = 2.0   # user explicitly follows this league
W_EXP_TEAM     = 3.0   # user explicitly follows this team
W_HIST_LEAGUE  = 1.0   # user has watched this league before
W_HIST_TEAM    = 1.5   # user has watched this team before


# ─────────────────────────────────────────────────────────────────────────────
# CACHE KEY
# ─────────────────────────────────────────────────────────────────────────────

def _cache_key(user_id: int) -> str:
    return f"short_feed:v3:{user_id}"


# ─────────────────────────────────────────────────────────────────────────────
# INTEREST VECTORS
# ─────────────────────────────────────────────────────────────────────────────

def _user_interest_leagues(user) -> list:
    """
    League IDs the user explicitly follows.
    favorite_league is a ForeignKey (single object), not ManyToMany —
    so we extract its pk directly and wrap in a list.
    Returns an empty list if the field is not set (null/blank allowed).
    """
    if user.favorite_league_id:          # uses the DB column directly — no extra query
        return [user.favorite_league_id]
    return []


def _user_interest_teams(user) -> list:
    """
    Team IDs the user explicitly follows.
    favorite_team is a ForeignKey (single object), not ManyToMany —
    same pattern as _user_interest_leagues.
    Returns an empty list if the field is not set (null/blank allowed).
    """
    if user.favorite_team_id:            # uses the DB column directly — no extra query
        return [user.favorite_team_id]
    return []


def _user_history_leagues(user, limit: int = HISTORY_LIMIT) -> list:
    """
    League IDs from videos the user has actually watched recently.
    Captures implicit interest: e.g. watched 5 La Liga clips → La Liga boost.
    """
    from .models import VideoView
    return list(
        VideoView.objects
        .filter(user=user, video__league__isnull=False)
        .values_list('video__league_id', flat=True)
        .order_by('-created_at')
        .distinct()[:limit]
    )


def _user_history_teams(user, limit: int = HISTORY_LIMIT) -> list:
    """Team IDs from videos the user has actually watched recently."""
    from .models import VideoView
    return list(
        VideoView.objects
        .filter(user=user, video__team__isnull=False)
        .values_list('video__team_id', flat=True)
        .order_by('-created_at')
        .distinct()[:limit]
    )


# ─────────────────────────────────────────────────────────────────────────────
# MAIN FEED FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def get_short_video_feed(user, limit: int = 20, bypass_cache: bool = False):
    """
    Returns an annotated ShortVideo queryset ordered by personalised score.

    All videos are fetched from the database — no external links (YouTube etc.)
    are used.  Content is ranked entirely by engagement signals + user
    preference vectors derived from followed leagues/teams and watch history.

    Steps
    ─────
    1. Check Redis cache — return preserved-order queryset on hit.
    2. Build user interest vectors (explicit follows + implicit watch history).
    3. Annotate engagement metrics using cached counters (O(1) reads) and
       avg_watch from VideoView rows.
    4. Compute watch_ratio (normalised 0-1 across any video length).
    5. Compute age_hours via EXTRACT(EPOCH ...) / 3600 — works correctly
       with PostgreSQL's interval type (no type-cast errors).
    6. Cap age_hours at AGE_DECAY_CAP_HRS so very old videos aren't buried.
    7. Annotate personalisation boosts.
    8. Compute final score, order descending, slice to `limit`.
    9. Store ordered UUID list in Redis and return queryset.
    """
    cache_key = _cache_key(user.pk)

    if not bypass_cache:
        cached_ids = cache.get(cache_key)
        if cached_ids:
            return _preserve_order_queryset(cached_ids)

    now = timezone.now()

    # ── 1. Interest vectors ──────────────────────────────────────────────────
    explicit_leagues = _user_interest_leagues(user)
    explicit_teams   = _user_interest_teams(user)
    history_leagues  = _user_history_leagues(user)
    history_teams    = _user_history_teams(user)

    # ── 2. Base queryset ─────────────────────────────────────────────────────
    qs = ShortVideo.objects.select_related('author', 'league', 'team')

    # ── 3. Engagement annotations ────────────────────────────────────────────
    # Use cached_* counters so we avoid expensive COUNT() aggregates per row.
    # avg_watch is the one place we hit the VideoView table — but it's a
    # single Avg() per video, not a subquery per request.
    qs = qs.annotate(
        likes_count    = F('cached_likes'),
        comments_count = F('cached_comments'),
        shares_count   = F('cached_shares'),
        views_count    = F('cached_views'),
        avg_watch      = Coalesce(
            Avg('views__watch_time'),
            Value(0.0),
            output_field=FloatField(),
        ),
    )

    # ── 4. watch_ratio  (clamped: 0 if duration == 0) ───────────────────────
    # Works correctly for shorts of any length (seconds → 2 hrs).
    qs = qs.annotate(
        watch_ratio=ExpressionWrapper(
            Case(
                When(duration__gt=0, then=F('avg_watch') / F('duration')),
                default=Value(0.0),
                output_field=FloatField(),
            ),
            output_field=FloatField(),
        )
    )

    # ── 5. Age in hours via EXTRACT(EPOCH FROM (now - created_at)) / 3600 ───
    #
    # FIX: The previous approach used Django timedelta division
    #   (now - F('created_at')) / 3_600_000_000
    # which produces a PostgreSQL `interval` type. Postgres cannot compare
    # `interval > numeric` directly, raising:
    #   ProgrammingError: operator does not exist: interval > numeric
    #
    # The correct approach is to use Extract('epoch') which calls
    #   EXTRACT(EPOCH FROM (now - created_at))
    # returning total seconds as a plain float, then divide by 3600 for hours.
    # This is the standard PostgreSQL way to convert an interval to a number.
    qs = qs.annotate(
        age_seconds=ExpressionWrapper(
            Extract(now - F('created_at'), 'epoch'),
            output_field=FloatField(),
        )
    )
    qs = qs.annotate(
        age_hours_raw=ExpressionWrapper(
            F('age_seconds') / 3600.0,
            output_field=FloatField(),
        )
    )

    # ── 6. Cap age at AGE_DECAY_CAP_HRS ─────────────────────────────────────
    # Prevents very old videos from accumulating an unbounded negative penalty.
    qs = qs.annotate(
        age_hours=Case(
            When(age_hours_raw__gt=AGE_DECAY_CAP_HRS, then=Value(AGE_DECAY_CAP_HRS)),
            default=F('age_hours_raw'),
            output_field=FloatField(),
        )
    )

    # ── 7. Personalisation boosts ────────────────────────────────────────────
    # Explicit follows carry higher weight than implicit watch-history signals.
    # If explicit_leagues / explicit_teams is empty the Case falls through to
    # default=0.0 cleanly — no SQL error from an empty __in list.
    qs = qs.annotate(
        explicit_league_boost=Case(
            When(league_id__in=explicit_leagues, then=Value(W_EXP_LEAGUE)),
            default=Value(0.0),
            output_field=FloatField(),
        ),
        explicit_team_boost=Case(
            When(team_id__in=explicit_teams, then=Value(W_EXP_TEAM)),
            default=Value(0.0),
            output_field=FloatField(),
        ),
        history_league_boost=Case(
            When(league_id__in=history_leagues, then=Value(W_HIST_LEAGUE)),
            default=Value(0.0),
            output_field=FloatField(),
        ),
        history_team_boost=Case(
            When(team_id__in=history_teams, then=Value(W_HIST_TEAM)),
            default=Value(0.0),
            output_field=FloatField(),
        ),
    )

    qs = qs.annotate(
        interest_boost=ExpressionWrapper(
            F('explicit_league_boost') + F('explicit_team_boost') +
            F('history_league_boost') + F('history_team_boost'),
            output_field=FloatField(),
        )
    )

    # ── 8. Final score ───────────────────────────────────────────────────────
    qs = qs.annotate(
        score=ExpressionWrapper(
            F('watch_ratio')    * W_WATCH_RATIO +
            F('likes_count')    * W_LIKES       +
            F('comments_count') * W_COMMENTS    +
            F('shares_count')   * W_SHARES      +
            F('age_hours')      * -AGE_DECAY_PER_HOUR +
            F('interest_boost'),
            output_field=FloatField(),
        )
    ).order_by('-score')

    # ── 9. Slice, cache and return ───────────────────────────────────────────
    result = qs[:limit]

    ids = [str(v.id) for v in result]   # evaluates the queryset once
    cache.set(cache_key, ids, CACHE_TTL)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# CACHE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _preserve_order_queryset(ids: list):
    """
    Re-fetch videos from cache hit, preserving the previously scored order
    via a CASE WHEN … expression (no re-scoring needed).
    """
    import uuid as _uuid

    uuid_ids  = [_uuid.UUID(i) for i in ids]
    order_expr = Case(
        *[When(pk=pk, then=Value(i)) for i, pk in enumerate(uuid_ids)],
        output_field=IntegerField(),
    )
    return (
        ShortVideo.objects
        .filter(pk__in=uuid_ids)
        .select_related('author', 'league', 'team')
        .annotate(
            likes_count    = F('cached_likes'),
            comments_count = F('cached_comments'),
            shares_count   = F('cached_shares'),
            views_count    = F('cached_views'),
        )
        .annotate(order=order_expr)
        .order_by('order')
    )


def bust_feed_cache(user_id: int):
    """Delete the cached feed list for a specific user."""
    cache.delete(_cache_key(user_id))