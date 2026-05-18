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
  watch_ratio normalises completion rate across all lengths.

Caching:
  - Feed IDs cached in Redis for 5 minutes per user (CACHE_TTL).
  - Cache busted on new video creation (via signal in signals.py).
  - bypass_cache=True forces a fresh query (useful for testing / admin).

Feed size:
  FEED_FETCH_SIZE (default 200) controls how many scored candidates the
  algorithm fetches. The view's LimitOffsetPaginator then slices those into
  pages. This constant is exported so views.py can import it.

Fixes applied
─────────────
  FIX-4  get_short_video_feed() no longer accepts a `limit` parameter.
         The old code sliced the queryset to `limit` rows (page size) before
         returning it. When the paginator then tried to apply an offset for
         page 2, it ran out of rows and returned an empty list. The algorithm
         now always fetches FEED_FETCH_SIZE scored candidates and returns them
         as a plain Python list. LimitOffsetPagination in the view does all
         page slicing.

  FIX-5  The queryset is now evaluated exactly once with list(qs[:FEED_FETCH_SIZE]).
         Previously `result = qs[:limit]` was returned un-evaluated; the
         caller iterated it to build the cache (first DB hit), then the view
         iterated it again to serialize (second identical DB hit). Evaluating
         once and returning a list costs nothing extra and halves DB load.
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
AGE_DECAY_PER_HOUR = 0.3           # score penalty per hour of age
AGE_DECAY_CAP_HRS  = 24.0          # decay stops after 24 h
HISTORY_LIMIT      = 10            # recent watched leagues/teams to consider

# FIX-4/FIX-5: fetch this many scored candidates; paginator slices the pages.
# Exported so views.py can reference it without magic numbers.
FEED_FETCH_SIZE    = 200

# Engagement weights
W_WATCH_RATIO  = 4.0
W_LIKES        = 2.0
W_COMMENTS     = 3.0
W_SHARES       = 5.0

# Personalisation weights
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
    favorite_league is a ForeignKey (single object) — extract pk directly.
    """
    if user.favorite_league_id:
        return [user.favorite_league_id]
    return []


def _user_interest_teams(user) -> list:
    """
    Team IDs the user explicitly follows.
    favorite_team is a ForeignKey (single object) — extract pk directly.
    """
    if user.favorite_team_id:
        return [user.favorite_team_id]
    return []


def _user_history_leagues(user, limit: int = HISTORY_LIMIT) -> list:
    """League IDs from videos the user has watched recently (implicit interest)."""
    from .models import VideoView
    return list(
        VideoView.objects
        .filter(user=user, video__league__isnull=False)
        .values_list('video__league_id', flat=True)
        .order_by('-created_at')
        .distinct()[:limit]
    )


def _user_history_teams(user, limit: int = HISTORY_LIMIT) -> list:
    """Team IDs from videos the user has watched recently (implicit interest)."""
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

def get_short_video_feed(user, bypass_cache: bool = False) -> list:
    """
    Returns a plain Python list of ShortVideo instances ordered by personalised
    score. The list always contains up to FEED_FETCH_SIZE items; the view's
    LimitOffsetPaginator slices it into pages.

    FIX-4: `limit` parameter removed. The old signature was:
        get_short_video_feed(user, limit=20, bypass_cache=False)
    Callers that passed limit= will need to remove that argument.

    FIX-5: The queryset is evaluated exactly once via list(qs[:FEED_FETCH_SIZE])
    and that list is both cached and returned. No second DB hit in the view.

    Steps
    ─────
    1. Check Redis cache — return preserved-order list on hit.
    2. Build user interest vectors (explicit follows + watch history).
    3. Annotate engagement metrics from cached_* columns (O(1) reads) and
       avg_watch from VideoView rows.
    4. Compute watch_ratio (normalised 0–1 across any video length).
    5. Compute age_hours via EXTRACT(EPOCH ...) / 3600 — avoids the
       PostgreSQL interval > numeric type error from timedelta division.
    6. Cap age_hours at AGE_DECAY_CAP_HRS.
    7. Annotate personalisation boosts.
    8. Compute final score, order descending.
    9. Evaluate to list, cache UUID list, return list.
    """
    cache_key = _cache_key(user.pk)

    if not bypass_cache:
        cached_ids = cache.get(cache_key)
        if cached_ids:
            return _preserve_order_list(cached_ids)

    now = timezone.now()

    # ── 1. Interest vectors ──────────────────────────────────────────────────
    explicit_leagues = _user_interest_leagues(user)
    explicit_teams   = _user_interest_teams(user)
    history_leagues  = _user_history_leagues(user)
    history_teams    = _user_history_teams(user)

    # ── 2. Base queryset with N+1 fixes ─────────────────────────────────────
    # author__profile: avatar in 1 JOIN (no per-video query for get_author_avatar)
    # prefetch likes: get_is_liked uses prefetch cache (no per-video .exists())
    qs = ShortVideo.objects.select_related(
        'author',
        'author__profile',
        'league',
        'team',
    ).prefetch_related(
        'likes',
    )

    # ── 3. Engagement annotations ────────────────────────────────────────────
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

    # ── 4. watch_ratio (clamped: 0 if duration == 0) ────────────────────────
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
    # Avoids PostgreSQL "operator does not exist: interval > numeric" error
    # that occurs when dividing a timedelta by an integer directly in ORM.
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
    qs = qs.annotate(
        age_hours=Case(
            When(age_hours_raw__gt=AGE_DECAY_CAP_HRS, then=Value(AGE_DECAY_CAP_HRS)),
            default=F('age_hours_raw'),
            output_field=FloatField(),
        )
    )

    # ── 7. Personalisation boosts ────────────────────────────────────────────
    # Empty __in lists fall through to default=0.0 cleanly — no SQL error.
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

    # ── 9. Evaluate once, cache, return ─────────────────────────────────────
    # FIX-5: list() evaluates the queryset a single time.
    # The view receives a plain list — no second DB hit when paginator
    # or serializer iterates it.
    result = list(qs[:FEED_FETCH_SIZE])

    ids = [str(v.id) for v in result]
    cache.set(cache_key, ids, CACHE_TTL)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# CACHE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _preserve_order_list(ids: list) -> list:
    """
    Re-fetch videos from a cache hit, preserving the previously scored order
    via a CASE WHEN expression (no re-scoring needed).

    FIX-5: Returns a plain Python list (consistent with the scored path) so
    the view always receives a list regardless of cache hit/miss.
    """
    import uuid as _uuid

    uuid_ids   = [_uuid.UUID(i) for i in ids]
    order_expr = Case(
        *[When(pk=pk, then=Value(i)) for i, pk in enumerate(uuid_ids)],
        output_field=IntegerField(),
    )
    qs = (
        ShortVideo.objects
        .filter(pk__in=uuid_ids)
        .select_related(
            'author',
            'author__profile',
            'league',
            'team',
        )
        .prefetch_related(
            'likes',
        )
        .annotate(
            likes_count    = F('cached_likes'),
            comments_count = F('cached_comments'),
            shares_count   = F('cached_shares'),
            views_count    = F('cached_views'),
        )
        .annotate(order=order_expr)
        .order_by('order')
    )
    return list(qs)   # FIX-5: evaluate to list here too


def bust_feed_cache(user_id: int) -> None:
    """Delete the cached feed list for a specific user."""
    cache.delete(_cache_key(user_id))