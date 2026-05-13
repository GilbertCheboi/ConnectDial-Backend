"""
Run this on your server to pinpoint the upload failure:

python manage.py shell < debug_upload.py

It will tell you EXACTLY where the chain breaks:
1. Can Django write to GCS at all?
2. Is the PostMedia model saving correctly?
3. Is the serializer excluding media_file from writable fields?
"""

import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'connectdial.settings')

from django.core.files.base import ContentFile
from posts.models import Post, PostMedia
from django.contrib.auth import get_user_model

User = get_user_model()

print("\n" + "="*60)
print("STEP 1: Check DEFAULT_FILE_STORAGE / STORAGES setting")
print("="*60)
from django.conf import settings
storages = getattr(settings, 'STORAGES', {})
default_storage = storages.get('default', {}).get('BACKEND', 'NOT SET')
print(f"Default storage backend: {default_storage}")
media_url = getattr(settings, 'MEDIA_URL', 'NOT SET')
print(f"MEDIA_URL: {media_url}")
gcs_bucket = getattr(settings, 'GS_BUCKET_NAME', 'NOT SET')
print(f"GCS Bucket: {gcs_bucket}")
gcs_key = getattr(settings, 'GS_KEY_PATH', 'NOT SET')
print(f"GCS Key path exists: {os.path.exists(gcs_key)}")

print("\n" + "="*60)
print("STEP 2: Try writing a test file directly to storage")
print("="*60)
from django.core.files.storage import default_storage
try:
    test_content = ContentFile(b"hello connectdial test")
    saved_name = default_storage.save("test_upload_debug.txt", test_content)
    saved_url = default_storage.url(saved_name)
    print(f"✅ Storage write SUCCESS")
    print(f"   Saved name : {saved_name}")
    print(f"   URL        : {saved_url}")
    # Cleanup
    default_storage.delete(saved_name)
    print(f"   Cleanup    : deleted test file")
except Exception as e:
    print(f"❌ Storage write FAILED: {type(e).__name__}: {e}")
    print("   → This is your root cause. Fix GCS credentials/permissions first.")

print("\n" + "="*60)
print("STEP 3: Check PostSerializer — is media_file read_only?")
print("="*60)
from posts.serializers import PostSerializer
s = PostSerializer()
writable_fields = {name: f for name, f in s.fields.items() if not getattr(f, 'read_only', False)}
readonly_fields = {name: f for name, f in s.fields.items() if getattr(f, 'read_only', False)}
print(f"Read-only fields  : {list(readonly_fields.keys())}")
print(f"Writable fields   : {list(writable_fields.keys())}")
if 'media_file' in readonly_fields:
    print("⚠️  'media_file' is READ-ONLY in the serializer — it will be IGNORED on create!")
    print("   Fix: Remove 'media_file' from read_only_fields in PostSerializer.Meta")
elif 'media_file' in writable_fields:
    print("✅ 'media_file' is writable in the serializer")
else:
    print("ℹ️  'media_file' not in serializer fields at all (handled in perform_create kwargs)")

print("\n" + "="*60)
print("STEP 4: Try creating a PostMedia row directly")
print("="*60)
try:
    p = Post.objects.latest('created_at')
    print(f"Latest post id: {p.id} | post_type: {p.post_type} | media_file: '{p.media_file}'")

    # Try saving a fake file to PostMedia
    fake_file = ContentFile(b"\xff\xd8\xff fake jpeg bytes", name="test_postmedia.jpg")
    pm = PostMedia(post=p, media_type='image', order=99)
    try:
        pm.file.save("test_postmedia.jpg", fake_file, save=True)
        print(f"✅ PostMedia file saved! URL: {pm.file.url}")
        pm.delete()
        print("   Cleanup: PostMedia row deleted")
    except Exception as e:
        print(f"❌ PostMedia file save FAILED: {type(e).__name__}: {e}")
except Exception as e:
    print(f"❌ Could not get latest post: {e}")

print("\n" + "="*60)
print("STEP 5: Check GCS service account permissions")
print("="*60)
try:
    from google.cloud import storage as gcs
    from google.oauth2 import service_account
    creds = service_account.Credentials.from_service_account_file(
        settings.GS_KEY_PATH,
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    client = gcs.Client(credentials=creds, project=creds.project_id)
    bucket = client.bucket(settings.GS_BUCKET_NAME)
    blob = bucket.blob("_permission_check.txt")
    blob.upload_from_string(b"permission check")
    blob.delete()
    print("✅ GCS service account has write permission to bucket")
except Exception as e:
    print(f"❌ GCS permission check FAILED: {type(e).__name__}: {e}")
    print("   → Go to GCS Console → IAM → grant your service account 'Storage Object Admin'")

print("\n" + "="*60)
print("DIAGNOSIS COMPLETE")
print("="*60)