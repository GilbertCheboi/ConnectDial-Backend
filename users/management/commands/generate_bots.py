import random
import requests
import time
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from users.models import Profile, FanPreference
from leagues.models import League, Team

User = get_user_model()

class Command(BaseCommand):
    help = 'Generates high-fidelity bots (Fans, News, and Organizations)'

    def add_arguments(self, parser):
        parser.add_argument('total', type=int, help='Number of bots to create')

    def handle(self, *args, **options):
        total = options['total']
        
        # --- IDENTITY POOLS ---
        ke_first = ["Kevin", "Brian", "Evans", "Emmanuel", "Collins", "Victor", "Jane", "Mercy", "Faith", "Joy"]
        ke_ethnic = ["Kipchoge", "Moraa", "Kamau", "Njeri", "Odhiambo", "Makena", "Kibet", "Waweru"]
        
        int_first = ["Jordan", "LeBron", "Giannis", "Luka", "Zion", "Kyrie", "Lewis", "Max"]
        int_last = ["West", "Rivers", "Miller", "Stone", "Hamilton", "Verstappen", "Bryant"]

        # News & Org Names
        news_prefixes = ["Daily", "Global", "Sports", "Fanatic", "Inside", "The", "Rapid"]
        news_suffixes = ["News", "Updates", "Report", "Central", "Hub", "Network"]
        org_types = ["Foundation", "Academy", "Agency", "Group", "Sports Club"]

        leagues = list(League.objects.all())
        if not leagues:
            self.stdout.write(self.style.ERROR('❌ No leagues found.'))
            return

        headers = {'User-Agent': 'Mozilla/5.0...'}

        for i in range(total):
            # 1. DETERMINE ACCOUNT TYPE (Weighted)
            # 90% Fan, 7% News, 3% Organization
            rand_val = random.random()
            if rand_val < 0.90:
                acc_type = 'fan'
                badge = 'none'
            elif rand_val < 0.97:
                acc_type = 'news'
                badge = 'official'
            else:
                acc_type = 'organization'
                badge = 'verified'

            # 2. GENERATE IDENTITY BASED ON TYPE
            suffix = random.randint(1000, 9999)
            fav_league = random.choice(leagues)
            
            if acc_type == 'fan':
                is_international = random.random() < 0.25
                f_name = random.choice(int_first if is_international else ke_first)
                l_name = random.choice(int_last if is_international else ke_ethnic)
                display_name = f"{f_name} {l_name}"
                username = f"{f_name.lower()}_{l_name.lower()}_{suffix}"
                bio = f"Massive {fav_league.name} supporter. #ConnectDial"
                search_term = "portrait,person"
            
            elif acc_type == 'news':
                name_part = random.choice(news_prefixes)
                display_name = f"{name_part} {fav_league.name} {random.choice(news_suffixes)}"
                username = display_name.replace(" ", "_").lower() + f"_{suffix}"
                bio = f"Official source for all things {fav_league.name}. Breaking news and updates."
                search_term = "news,studio,microphone"

            else:  # Organization
                display_name = f"{fav_league.name} {random.choice(org_types)}"
                username = display_name.replace(" ", "_").lower() + f"_{suffix}"
                bio = f"Supporting the growth of {fav_league.name} worldwide. Official Account."
                search_term = "office,building,logo"

            # 3. DATABASE PERSISTENCE
            try:
                user = User.objects.create(
                    username=username,
                    email=f"bot_{suffix}@connectdial.com",
                    favorite_league=fav_league,
                    account_type=acc_type, # 🚀 Sets 'fan', 'news', or 'organization'
                    fan_badge=badge        # 🚀 Sets 'official', 'verified', etc.
                )
                user.set_password('connect_bot_2026')
                user.save()

                profile, _ = Profile.objects.get_or_create(user=user)
                profile.display_name = display_name
                profile.is_bot = True
                profile.bio = bio
                profile.save()

                # 4. VISUAL IDENTITY
                self.stdout.write(f"  [{i+1}/{total}] Creating {acc_type}: {username}...")
                
                # Dynamic Profile Image based on search_term
                try:
                    face_url = f"https://source.unsplash.com/featured/400x400/?{search_term}&sig={random.randint(1, 999)}"
                    face_res = requests.get(face_url, headers=headers, timeout=5)
                    if face_res.status_code == 200:
                        profile.profile_image.save(f"pfp_{user.id}.jpg", ContentFile(face_res.content), save=True)
                except:
                    pass

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"❌ Error: {e}"))

            time.sleep(1) # HP 290 Safety

        self.stdout.write(self.style.SUCCESS(f'✅ Finished generating {total} mixed-type bots.'))