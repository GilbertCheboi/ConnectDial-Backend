"""
State-only migration — no database changes.

The short_videos_videocomment table already has a `user_id` column (the FK
to users_user). The Python model field was named `author`, so Django assumed
the column was `author_id` and started generating broken SQL.

Fix: add db_column='user_id' to the model field so Django knows the column
name without needing to rename anything in the database.

This migration updates Django's migration state to record that db_column
is now set. It uses SeparateDatabaseAndState so that:
  - state_operations : Django's internal model state is updated (required
                       so future makemigrations doesn't regenerate this).
  - database_operations: empty list — zero SQL is executed against Postgres.
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('short_videos', '0004_videoview_completed'),   # ← adjust to your actual previous migration
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            # Tell Django's state tracker about the db_column so it stops
            # thinking the column needs to be called author_id.
            state_operations=[
                migrations.AlterField(
                    model_name='videocomment',
                    name='author',
                    field=models.ForeignKey(
                        db_column='user_id',
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='video_comments',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            # No SQL — the column is already correct in the database.
            database_operations=[],
        ),
    ]