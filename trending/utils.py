from django.db.models import Count, F, ExpressionWrapper, FloatField
from django.utils import timezone
from posts.models import Post

def get_trending_posts(limit=20, hours=48):
    """
    Trending algorithm:
    likes = 1 point
    comments = 2 points
    shares = 3 points
    decay over time
    """

    now = timezone.now()

    queryset = (
        Post.objects
        .filter(created_at__gte=now - timezone.timedelta(hours=hours))
        .annotate(
            likes_count=Count('likes', distinct=True),
            comments_count=Count('comments', distinct=True),
            shares_count=Count('shares', distinct=True),
        )
        .annotate(
            age_in_hours=ExpressionWrapper(
                (now - F('created_at')),
                output_field=FloatField()
            )
        )
        .annotate(
            trending_score=(
                F('likes_count') * 1 +
                F('comments_count') * 2 +
                F('shares_count') * 3 -
                (F('age_in_hours') / 3600) * 0.5
            )
        )
        .order_by('-trending_score')
    )

    return queryset[:limit]

