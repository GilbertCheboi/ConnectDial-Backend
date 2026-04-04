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
    help = 'Generates 10,000+ high-fidelity bots with Authentic Kenyan and International identities'

    def add_arguments(self, parser):
        parser.add_argument('total', type=int, help='Number of bots to create')

    def handle(self, *args, **options):
        total = options['total']
        
        # --- IDENTITY POOLS ---
        
        # Authentic Kenyan: English First + Traditional Surname
        ke_first = ["Kevin", "Brian", "John", "James", "Evans", "Emmanuel", "Geoffrey", "Collins", 
                    "Victor", "Peter", "David", "Joseph", "Mary", "Mercy", "Faith", "Alice", 
                    "Stacy", "Sharon", "Joy", "Grace", "Cynthia", "Beatrice", "Diana", "Phyllis"]
        
        ke_ethnic = ["Kipchoge", "Moraa", "Kamau", "Njeri", "Odhiambo", "Makena", "Kimani", "Syokau", 
                     "Mutua", "Chepngetich", "Kibet", "Waweru", "Atieno", "Maina", "Kariuki", 
                     "Otieno", "Wekesa", "Cheruiyot", "Nduta", "Keter", "Mulei", "Okafor", "Mboya"]
        
        # International (NBA/NFL/F1 focus)
        int_first = ["Jordan", "LeBron", "Dak", "Brady", "Giannis", "Sloane", "Cooper", "Xavier", 
                     "Skylar", "Jaxon", "Maddox", "Luka", "Zion", "Kyrie", "Tyreek", "Chase"]
        int_last = ["West", "Rivers", "Miller", "Stone", "Vettel", "Hamilton", "Ricciardo", 
                    "Verstappen", "Bryant", "James", "Mahomes", "Kelce", "Stroud", "Wolff"]

        leagues = list(League.objects.all())
        if not leagues:
            self.stdout.write(self.style.ERROR('❌ No leagues found. Ensure NBA, F1, etc. exist in DB.'))
            return

        self.stdout.write(f"🚀 Deploying {total} bots to ConnectDial (Target: PostgreSQL)...")

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36'
        }

        for i in range(total):
            # 1. WEIGHTED IDENTITY SELECTION (75% Kenyan / 25% International)
            is_international = random.random() < 0.25 
            
            if is_international:
                f_name = random.choice(int_first)
                l_name = random.choice(int_last)
                region_tag = random.choice(["American", "Hispanic", "European", "Mixed-race"])
            else:
                f_name = random.choice(ke_first)
                l_name = random.choice(ke_ethnic)
                region_tag = random.choice(["African", "Black"])

            # 2. CREDENTIALS (6-digit suffix for 10k scale safety)
            suffix = random.randint(100000, 999999)
            username = f"{f_name.lower()}_{l_name.lower()}_{suffix}"
            
            # 3. LEAGUE & TEAM ASSIGNMENT
            fav_league = random.choice(leagues)
            teams_in_league = list(Team.objects.filter(league=fav_league))
            
            if not teams_in_league:
                fav_team, _ = Team.objects.get_or_create(name=f"{fav_league.name} Fanatic", league=fav_league)
            else:
                fav_team = random.choice(teams_in_league)

            # 4. DATABASE PERSISTENCE
            try:
                user = User.objects.create(
                    username=username,
                    email=f"bot_{suffix}@connectdial.com",
                    favorite_league=fav_league,
                    favorite_team=fav_team,
                    fan_badge="Pro Fan"
                )
                user.set_password('connect_bot_2026')
                user.save()

                # 5. PROFILE CUSTOMIZATION
                profile, _ = Profile.objects.get_or_create(user=user)
                profile.display_name = f"{f_name} {l_name}"
                profile.is_bot = True
                
                # Variety in bios prevents "Uncanny Valley" effect
                bios = [
                    f"Massive {fav_team.name} supporter. Tracking {fav_league.name} 24/7! ⚽🏎️",
                    f"{fav_league.name} enthusiast. {fav_team.name} to the world! 😤",
                    f"Just here for the {fav_team.name} highlights. #ConnectDial",
                    f"Analyzing every {fav_league.name} play. Go {fav_team.name}!",
                    f"Game day is every day. 📍 Location: Kenya | Team: {fav_team.name}",
                    f"Stats, scores, and vibes. {fav_league.name} insider. 🏀"
                ]
                profile.bio = random.choice(bios)
                profile.save()

                # 6. VISUAL IDENTITY (Face + Stadium Banner)
                gender = random.choice(["man", "woman"])
                self.stdout.write(f"  [{i+1}/{total}] 📸 Fetching {region_tag} {gender} for {username}...")

                # --- PROFILE IMAGE (PFP) ---
                try:
                    # sig ensures unique image per request
                    face_url = f"https://source.unsplash.com/featured/400x400/?{region_tag},{gender},portrait&sig={random.randint(1, 99999)}"
                    face_res = requests.get(face_url, headers=headers, timeout=8, allow_redirects=True)
                    
                    if face_res.status_code != 200:
                        # Fallback if Unsplash throttles
                        face_res = requests.get(f"https://loremflickr.com/400/400/{region_tag},{gender},person/all", timeout=8)

                    if face_res.status_code == 200:
                        profile.profile_image.save(f"pfp_{user.id}.jpg", ContentFile(face_res.content), save=True)
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"    🚫 PFP skip: {e}"))

                # --- BANNER IMAGE ---
                try:
                    sport_key = fav_league.name.split()[0]
                    banner_url = f"https://loremflickr.com/1200/400/stadium,{sport_key}/all"
                    banner_res = requests.get(banner_url, timeout=8)
                    if banner_res.status_code == 200:
                        profile.banner_image.save(f"banner_{user.id}.jpg", ContentFile(banner_res.content), save=True)
                except:
                    pass

                # 7. LOG FAN PREFERENCE
                FanPreference.objects.get_or_create(user=user, league=fav_league, team=fav_team)

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"❌ Failed bot {username}: {e}"))

            # 8. RATE LIMIT PROTECTION
            # 1.2s sleep is recommended to avoid getting your IP banned by Unsplash/Flickr
            time.sleep(1.2)

        self.stdout.write(self.style.SUCCESS(f'✅ Successfully deployed {total} bots to the {fav_league.name} and beyond!'))