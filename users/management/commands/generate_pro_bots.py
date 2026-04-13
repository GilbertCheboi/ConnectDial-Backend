import random
import requests
import time
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from users.models import Profile
from leagues.models import League

User = get_user_model()

class Command(BaseCommand):
    help = 'Generates 20-30 Official News and Organization bots'

    def add_arguments(self, parser):
        parser.add_argument('total', type=int, help='Number of Pro bots to create')

    def handle(self, *args, **options):
        total = options['total']
        
        # --- IDENTITY POOLS ---
        news_prefixes = ["Daily", "Global", "Sports", "Fanatic", "Inside", "The", "Rapid", "Flash", "Elite"]
        news_suffixes = ["News", "Updates", "Report", "Central", "Hub", "Network", "Wire", "Desk"]
        org_types = ["Foundation", "Academy", "Agency", "Group", "Sports Club", "Association", "Institute"]

        leagues = list(League.objects.all())
        if not leagues:
            self.stdout.write(self.style.ERROR('❌ No leagues found in DB.'))
            return

        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

        self.stdout.write(f"🚀 Creating {total} Professional Accounts...")

        for i in range(total):
            # 50/50 split between News and Organization
            acc_type = 'news' if i % 2 == 0 else 'organization'
            badge = 'official' if acc_type == 'news' else 'verified'
            
            fav_league = random.choice(leagues)
            suffix = random.randint(100, 999)

            if acc_type == 'news':
                display_name = f"{random.choice(news_prefixes)} {fav_league.name} {random.choice(news_suffixes)}"
                bio = f"Verified {fav_league.name} news source. Stay updated with {display_name}."
                search_term = "news,studio,journalism"
            else:
                display_name = f"{fav_league.name} {random.choice(org_types)}"
                bio = f"Official {display_name} account. Promoting sports excellence in {fav_league.name}."
                search_term = "stadium,office,management"

            username = display_name.replace(" ", "_").lower() + f"_{suffix}"

            try:
                # Create the User
                user = User.objects.create(
                    username=username,
                    email=f"pro_bot_{suffix}@connectdial.com",
                    favorite_league=fav_league,
                    account_type=acc_type, # Assigns 'news' or 'organization'
                    fan_badge=badge        # Assigns 'official' or 'verified'
                )
                user.set_password('connect_pro_2026')
                user.save()

                # Create the Profile
                profile, _ = Profile.objects.get_or_create(user=user)
                profile.display_name = display_name
                profile.is_bot = True
                profile.bio = bio
                profile.save()

                self.stdout.write(f"  [{i+1}/{total}] Created {badge.upper()}: {display_name}")

                # Fetch Images (Profile Pic)
                try:
                    img_url = f"https://source.unsplash.com/featured/400x400/?{search_term}&sig={random.randint(1, 999)}"
                    res = requests.get(img_url, headers=headers, timeout=5)
                    if res.status_code == 200:
                        profile.profile_image.save(f"pro_{user.id}.jpg", ContentFile(res.content), save=True)
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"    ⚠️ Image skip: {e}"))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  ❌ Error creating {username}: {e}"))

            # Small delay for your HP 290
            time.sleep(1)

        self.stdout.write(self.style.SUCCESS(f'✅ Successfully deployed {total} Professional bots!'))