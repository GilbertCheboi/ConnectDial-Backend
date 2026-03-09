from django.db.models import Count, Avg, F, ExpressionWrapper, FloatField
from django.utils import timezone
from .models import ShortVideo

def get_short_video_feed(user, limit=20):
    now = timezone.now()

    user_leagues = user.favorite_leagues.values_list('id', flat=True)
    user_teams = user.favorite_teams.values_list('id', flat=True)

    queryset = (
        ShortVideo.objects
        .annotate(
            likes_count=Count('likes', distinct=True),
            comments_count=Count('comments', distinct=True),
            shares_count=Count('shares', distinct=True),
            avg_watch=Avg('views__watch_time'),
        )
        .annotate(
            watch_ratio=ExpressionWrapper(
                F('avg_watch') / F('duration'),
                output_field=FloatField()
            )
        )
        .annotate(
            age_hours=ExpressionWrapper(
                (now - F('created_at')),
                output_field=FloatField()
            )
        )
    )

    queryset = queryset.annotate(
        interest_boost=ExpressionWrapper(
            (
                models.Case(
                    models.When(league_id__in=user_leagues, then=2),
                    default=0,
                    output_field=FloatField()
                ) +
                models.Case(
                    models.When(team_id__in=user_teams, then=3),
                    default=0,
                    output_field=FloatField()
                )
            ),
            output_field=FloatField()
        )
    )

    queryset = queryset.annotate(
        score=(
            F('watch_ratio') * 4 +
            F('likes_count') * 2 +
            F('comments_count') * 3 +
            F('shares_count') * 5 -
            (F('age_hours') / 3600) * 0.3 +
            F('interest_boost')
        )
    ).order_by('-score')

    return queryset[:limit]

