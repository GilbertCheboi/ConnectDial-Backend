import random
import requests
import time
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from users.models import Profile

User = get_user_model()

class Command(BaseCommand):
    help = 'Assigns high-quality, diverse, real human photos with fallback logic for rate limits'

    def handle(self, *args, **options):
        # We only fix bots that are missing images to save bandwidth
        bots_to_fix = Profile.objects.filter(is_bot=True, profile_image="")
        
        if not bots_to_fix.exists():
            self.stdout.write(self.style.SUCCESS("✨ All bots already have profile pictures!"))
            return

        self.stdout.write(f"🌍 Starting global makeover for {bots_to_fix.count()} bots...")

        regions = ["African", "Black", "American", "Hispanic", "Mixed-race"]
        genders = ["man", "woman"]

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36'
        }

        for profile in bots_to_fix:
            username = profile.user.username
            region = random.choice(regions)
            gender = random.choice(genders)
            
            self.stdout.write(f"Updating {username} as {region} {gender}...")

            # --- DUAL-SOURCE IMAGE FETCHING ---
            # Try Unsplash first, fall back to Pexels/LoremFlickr if 503 occurs
            img_content = None
            
            # Source 1: Unsplash
            face_url = f"https://source.unsplash.com/featured/400x400/?{region},{gender},face,portrait&sig={random.randint(1, 10000)}"
            
            try:
                res = requests.get(face_url, headers=headers, timeout=15, allow_redirects=True)
                
                if res.status_code == 200:
                    img_content = res.content
                elif res.status_code == 503:
                    self.stdout.write(self.style.WARNING("  ⚠️ Unsplash throttled (503). Switching to Fallback..."))
                    # Source 2: LoremFlickr (Less strict on rate limits)
                    fallback_url = f"https://loremflickr.com/400/400/{region},{gender},person/all"
                    res = requests.get(fallback_url, timeout=15)
                    if res.status_code == 200:
                        img_content = res.content
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  ❌ Source failed: {e}"))

            # Save if we got an image
            if img_content:
                profile.profile_image.save(f"pfp_{profile.user.id}.jpg", ContentFile(img_content), save=True)
                self.stdout.write(f"  ✅ Face assigned.")
            else:
                self.stdout.write(self.style.ERROR("  🚫 Could not retrieve any image for this bot."))

            # --- STADIUM BANNER ---
            try:
                league_name = profile.user.favorite_league.name if profile.user.favorite_league else "sports"
                sport_keyword = league_name.split()[0]
                banner_url = f"https://loremflickr.com/1200/400/stadium,{sport_keyword}/all"
                
                banner_res = requests.get(banner_url, timeout=15)
                if banner_res.status_code == 200:
                    profile.banner_image.save(f"banner_{profile.user.id}.jpg", ContentFile(banner_res.content), save=True)
                    self.stdout.write(f"  ✅ Banner assigned.")
            except:
                pass

            # CRITICAL: Wait 2 seconds between bots to prevent your IP from being banned
            time.sleep(2)

        self.stdout.write(self.style.SUCCESS(f"✅ Deployment complete! Check your app now."))