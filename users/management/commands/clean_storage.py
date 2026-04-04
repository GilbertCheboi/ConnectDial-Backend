import os
from django.core.management.base import BaseCommand
from django.utils import timezone
from posts.models import Post
from django.conf import settings

class Command(BaseCommand):
    help = 'Deletes bot-generated shorts and media older than 7 days to save Firebase costs'

    def handle(self, *args, **options):
        # 1. Define the expiration threshold
        expiry_date = timezone.now() - timezone.timedelta(days=7)

        # 2. Find old bot posts with media
        # We only target bots to avoid deleting real user content accidentally
        old_posts = Post.objects.filter(
            created_at__lt=expiry_date,
            author__profile__is_bot=True
        )

        count = old_posts.count()
        if count == 0:
            self.stdout.write(self.style.SUCCESS("✨ Storage is already clean. No old bot media found."))
            return

        self.stdout.write(f"🧹 Found {count} old bot posts. Starting cleanup...")

        for post in old_posts:
            try:
                # 3. Delete the file from Firebase Storage
                # Django-storages handles the cloud deletion when you call .delete()
                if post.media_file:
                    self.stdout.write(f"  🗑️ Deleting cloud file: {post.media_file.name}")
                    post.media_file.delete(save=False)
                
                # 4. Delete the database record
                post.delete()
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  ❌ Error deleting post {post.id}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"✅ Successfully cleared {count} posts from Firebase and Database."))