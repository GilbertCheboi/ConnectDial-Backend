"""
ConnectDial — engagement_models.py
=====================================
THIS FILE HAS BEEN DELETED.

All engagement models (VideoLike, VideoComment, CommentMention, VideoShare,
VideoView) now live in models.py, which is the single canonical source of
truth.

Why it was removed
──────────────────
engagement_models.py was a stale duplicate that diverged from models.py:

  - VideoComment used `text = models.TextField()` here vs
    `body = models.TextField(db_column='text')` in models.py (with parent,
    mentioned_users M2M, UUID pk, and threading support).

  - VideoLike, VideoShare, and VideoView were also out of sync.

If Django ever registered both files as separate apps/modules, it would raise
a duplicate model error. If any import pulled from the wrong file, the schema
mismatch would cause silent data corruption or runtime errors.

Action required
───────────────
  1. Delete this file from your repository entirely.
  2. Ensure all imports point to .models, never to .engagement_models.

     WRONG:  from .engagement_models import VideoLike
     RIGHT:  from .models import VideoLike

  3. If you have a migration that references engagement_models, rename the
     app_label in that migration to match the app that owns models.py.
"""

# This file intentionally left with no importable symbols.
# Delete it — do not import from it.
raise ImportError(
    "engagement_models.py is a stale duplicate and must be deleted. "
    "Import all engagement models from .models instead."
)