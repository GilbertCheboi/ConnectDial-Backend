import os
from django.core.management.base import BaseCommand
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.conf import settings
from posts.models import Post

class Command(BaseCommand):
    help = 'Uploads local media files to Firebase and updates database URLs'

    def handle(self, *args, **options):
        # 1. Find posts with local files (exclude absolute http URLs)
        posts = Post.objects.filter(media_file__isnull=False).exclude(media_file__icontains='http')

        if not posts.exists():
            self.stdout.write(self.style.SUCCESS("✅ No local files found to migrate."))
            return

        self.stdout.write(f"🚀 Found {posts.count()} potential files. Starting migration...")

        success_count = 0
        skip_count = 0

        for post in posts:
            try:
                # SAFETY CHECK: Does the FileField actually point to a file?
                if not post.media_file or not post.media_file.name:
                    skip_count += 1
                    continue

                # Check if file exists on HP 290 disk
                local_path = post.media_file.path
                if not os.path.exists(local_path):
                    self.stdout.write(self.style.WARNING(f"  ⏩ Missing on disk (ID {post.id}): {local_path}"))
                    skip_count += 1
                    continue
                
                # 2. Read and Upload
                self.stdout.write(f"  📤 Uploading: {post.media_file.name}...")
                with open(local_path, 'rb') as f:
                    content = ContentFile(f.read())
                    # Saves to Firebase via settings.DEFAULT_FILE_STORAGE
                    new_path = default_storage.save(post.media_file.name, content)
                    
                    # Update DB to the new cloud path
                    post.media_file = new_path
                    post.save()
                    
                success_count += 1
                self.stdout.write(self.style.SUCCESS(f"  ✅ Successfully migrated to Firebase."))

            except ValueError:
                self.stdout.write(self.style.ERROR(f"  ❌ Post {post.id} has no file associated. Skipping."))
                skip_count += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  ❌ Error on Post {post.id}: {str(e)}"))

        self.stdout.write(self.style.SUCCESS(f"🏁 Done! Migrated: {success_count}, Skipped: {skip_count}"))