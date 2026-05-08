"""
Streaming utilities for ConnectDial short videos.

Supports HTTP Range requests so the mobile player can:
  • Seek without re-downloading
  • Start playing before the full file is downloaded (progressive playback)
  • Resume after network interruptions

Storage backend compatibility
──────────────────────────────
video_file.path  works ONLY with Django's local FileSystemStorage.
video_file.url   works with ANY backend (local, S3, GCS, Azure, etc.)

This module uses .url for all cases:
  - If the URL is an S3/GCS presigned URL → redirect directly (no proxying)
  - If the URL is a local MEDIA_URL path  → serve the file via Django with
    Range support (dev only; use a real CDN in production)

Usage in views:
    return stream_video_response(request, video)
"""

import os
import mimetypes
from urllib.parse import urlparse

from django.http import StreamingHttpResponse, HttpResponseRedirect
from django.conf import settings


CHUNK_SIZE = 1024 * 512  # 512 KB chunks


def _is_external_url(url: str) -> bool:
    """
    Returns True if the URL points to an external host (S3, GCS, CDN, etc.)
    rather than our own Django server.
    """
    parsed = urlparse(url)
    return parsed.scheme in ('http', 'https') and bool(parsed.netloc)


def stream_video_response(request, video_instance):
    """
    Returns a streaming response for the video file.

    Strategy
    ────────
    1. Get the file URL via video_file.url — works with any storage backend.
    2. If it's an external URL (S3 presigned, GCS signed, CDN) → redirect.
       The mobile player follows the redirect and streams directly from the
       CDN — no proxying through Django.
    3. If it's a local MEDIA_URL path → resolve to an absolute filesystem
       path using MEDIA_ROOT and serve with Range support (dev mode).
    """
    video_file = video_instance.video

    if not video_file or not video_file.name:
        from rest_framework.response import Response
        from rest_framework import status
        return Response(
            {'detail': 'No video file attached to this record.'},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Get the URL — works with FileSystemStorage, S3Boto3Storage, GCSStorage, etc.
    file_url = video_file.url

    # ── External storage (S3, GCS, Azure, CDN) ───────────────────────────────
    # The storage backend returns a full URL (possibly presigned).
    # Redirect the player — it streams directly from the CDN; Django doesn't
    # proxy the bytes. This is the production path.
    if _is_external_url(file_url):
        return HttpResponseRedirect(file_url)

    # ── Local / dev storage (FileSystemStorage) ───────────────────────────────
    # file_url is something like /media/shorts/uuid/abc.mp4
    # Resolve to an absolute path using MEDIA_ROOT.
    media_root = getattr(settings, 'MEDIA_ROOT', '')
    if not media_root:
        from rest_framework.response import Response
        from rest_framework import status
        return Response(
            {'detail': 'MEDIA_ROOT is not configured. Cannot serve local video files.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # Strip the MEDIA_URL prefix to get the relative path, then join with MEDIA_ROOT.
    media_url = getattr(settings, 'MEDIA_URL', '/media/')
    relative_path = video_file.name   # e.g. "shorts/uuid/abc.mp4"
    file_path = os.path.join(media_root, relative_path)

    if not os.path.exists(file_path):
        from rest_framework.response import Response
        from rest_framework import status
        return Response(
            {'detail': 'Video file not found on disk.'},
            status=status.HTTP_404_NOT_FOUND,
        )

    file_size = os.path.getsize(file_path)
    content_type, _ = mimetypes.guess_type(file_path)
    content_type = content_type or 'video/mp4'

    range_header = request.META.get('HTTP_RANGE', '').strip()

    if range_header:
        # Parse "bytes=start-end"
        byte_range = range_header.replace('bytes=', '')
        start_str, _, end_str = byte_range.partition('-')
        start = int(start_str) if start_str else 0
        end   = int(end_str)   if end_str   else file_size - 1
        end   = min(end, file_size - 1)
        length = end - start + 1

        def file_iterator(path, start, length, chunk=CHUNK_SIZE):
            with open(path, 'rb') as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    data = f.read(min(chunk, remaining))
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        response = StreamingHttpResponse(
            file_iterator(file_path, start, length),
            status=206,
            content_type=content_type,
        )
        response['Content-Length'] = str(length)
        response['Content-Range']  = f'bytes {start}-{end}/{file_size}'
        response['Accept-Ranges']  = 'bytes'
        response['Cache-Control']  = 'public, max-age=86400'
        return response

    # Full file (no Range header)
    def full_iterator(path, chunk=CHUNK_SIZE):
        with open(path, 'rb') as f:
            while True:
                data = f.read(chunk)
                if not data:
                    break
                yield data

    response = StreamingHttpResponse(full_iterator(file_path), content_type=content_type)
    response['Content-Length'] = str(file_size)
    response['Accept-Ranges']  = 'bytes'
    response['Cache-Control']  = 'public, max-age=86400'
    return response


def build_whatsapp_share_text(video):
    """
    WhatsApp / Telegram plain-text share preview.
    Message format:
        🎬 [Video] ConnectDial
        👤 @username
        🏆 Champions League • Chelsea FC
        📝 Caption truncated here...
        ▶️ Watch: https://connectdial.com/shorts/uuid/
    """
    lines = [
        "🎬 *[Video]* ConnectDial",
        f"👤 @{video.author.username}",
    ]
    if video.league or video.team:
        ctx = " • ".join(filter(None, [
            video.league.name if video.league else None,
            video.team.name  if video.team   else None,
        ]))
        lines.append(f"🏆 {ctx}")
    if video.caption:
        caption = video.caption[:120] + ("…" if len(video.caption) > 120 else "")
        lines.append(f"📝 {caption}")
    lines.append(f"▶️ Watch: {video.share_url}")
    return "\n".join(lines)


def build_telegram_share_text(video):
    """Telegram supports HTML mode — include bold/links."""
    league_team = " | ".join(filter(None, [
        video.league.name if video.league else None,
        video.team.name   if video.team   else None,
    ]))
    caption = video.caption[:100] + "…" if len(video.caption) > 100 else video.caption
    text = (
        f"🎬 <b>[Video]</b> ConnectDial\n"
        f"👤 <b>@{video.author.username}</b>\n"
    )
    if league_team:
        text += f"🏆 {league_team}\n"
    if caption:
        text += f"📝 {caption}\n"
    text += f'▶️ <a href="{video.share_url}">Watch on ConnectDial</a>'
    return text