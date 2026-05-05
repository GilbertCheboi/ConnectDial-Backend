"""
Streaming utilities for ConnectDial short videos.

Supports HTTP Range requests so the mobile player can:
  • Seek without re-downloading
  • Start playing before the full file is downloaded (progressive playback)
  • Resume after network interruptions

Usage in views:
    return stream_video_response(request, video)
"""

import os
import mimetypes
from django.http import StreamingHttpResponse, HttpResponse
from django.conf import settings


CHUNK_SIZE = 1024 * 512  # 512 KB chunks


def stream_video_response(request, video_instance):
    """
    Returns a StreamingHttpResponse with Range support.
    Works with Django's default FileSystemStorage.
    For production, point to S3/GCS presigned URLs instead.
    """
    video_file = video_instance.video

    # --- Production shortcut: return presigned URL redirect ---
    if getattr(settings, 'USE_S3', False):
        import boto3
        s3 = boto3.client('s3')
        url = s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': settings.AWS_STORAGE_BUCKET_NAME, 'Key': video_file.name},
            ExpiresIn=3600
        )
        from django.http import HttpResponseRedirect
        return HttpResponseRedirect(url)

    # --- Local / dev streaming ---
    file_path = video_file.path
    file_size = os.path.getsize(file_path)
    content_type, _ = mimetypes.guess_type(file_path)
    content_type = content_type or 'video/mp4'

    range_header = request.META.get('HTTP_RANGE', '').strip()

    if range_header:
        # Parse "bytes=start-end"
        byte_range = range_header.replace('bytes=', '')
        start_str, _, end_str = byte_range.partition('-')
        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else file_size - 1
        end = min(end, file_size - 1)
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
            content_type=content_type
        )
        response['Content-Length'] = str(length)
        response['Content-Range'] = f'bytes {start}-{end}/{file_size}'
        response['Accept-Ranges'] = 'bytes'
        response['Cache-Control'] = 'public, max-age=86400'
        return response

    # Full file response
    def full_iterator(path, chunk=CHUNK_SIZE):
        with open(path, 'rb') as f:
            while True:
                data = f.read(chunk)
                if not data:
                    break
                yield data

    response = StreamingHttpResponse(full_iterator(file_path), content_type=content_type)
    response['Content-Length'] = str(file_size)
    response['Accept-Ranges'] = 'bytes'
    response['Cache-Control'] = 'public, max-age=86400'
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
            video.team.name if video.team else None,
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
        video.team.name if video.team else None,
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