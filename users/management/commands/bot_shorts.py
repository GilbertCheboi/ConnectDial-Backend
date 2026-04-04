import random
import requests
import time
import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from posts.models import Post, Hashtag
from leagues.models import League, Team

User = get_user_model()

class Command(BaseCommand):
    help = 'Fetches real sports vertical videos from Pexels and uploads them to Firebase'

    def add_arguments(self, parser):
        parser.add_argument('league_name', type=str)

    def handle(self, *args, **options):
        league_query = options['league_name']
        # 🔑 Your Pexels Key
        PEXELS_API_KEY = "HNdRlaon0CTc9qoCrFUYUNrnrHV6wpyetmhozjBUhpZ9tnVPPvZIBWO5" 
        
        # 1. League Alignment
        league = League.objects.filter(name__icontains=league_query).first()
        if not league:
            self.stdout.write(self.style.ERROR(f"League '{league_query}' not found in database."))
            return
        
        # 2. Find a Bot User
        bot_user = User.objects.filter(
            profile__is_bot=True, 
            favorite_league=league
        ).order_by('?').first()

        if not bot_user:
            bot_user = User.objects.filter(profile__is_bot=True).order_by('?').first()
            if not bot_user:
                self.stdout.write(self.style.ERROR("No bot accounts found."))
                return

        self.stdout.write(f"🎬 Bot @{bot_user.username} searching highlights for {league.name}...")
        
        # 3. Dynamic Search Terms
        search_term = league.name.lower()
        if any(x in search_term for x in ["premier", "liga", "champions", "soccer"]):
            search_term = "soccer"
        elif "nba" in search_term:
            search_term = "basketball"
        elif "f1" in search_term:
            search_term = "formula 1"

        url = f"https://api.pexels.com/videos/search?query={search_term}&orientation=portrait&per_page=15"
        headers = {"Authorization": PEXELS_API_KEY}

        try:
            res = requests.get(url, headers=headers, timeout=15).json()
            videos = res.get('videos', [])
            
            if not videos:
                self.stdout.write(self.style.WARNING(f"No vertical videos found for {search_term}."))
                return

            # Pick a random video and find a mobile-friendly resolution (under 1000px width)
            video_data = random.choice(videos)
            video_files = video_data.get('video_files', [])
            video_url = next((v['link'] for v in video_files if v['width'] < 1000), video_files[0]['link'])
            
            # 4. Stream the Video Bytes
            self.stdout.write(f"⏳ Downloading video from Pexels...")
            vid_res = requests.get(video_url, stream=True, timeout=60)
            
            if vid_res.status_code == 200:
                # 🚀 THE CRITICAL PATH ALIGNMENT:
                # Since Model has upload_to='post_media/', we provide only the sub-path.
                # Final structure: bucket/post_media/shorts/league_X/bot_Y.mp4
                file_path = f"shorts/league_{league.id}/bot_{bot_user.id}_{int(time.time())}.mp4"
                
                # 5. Create the Post Object but don't save media yet
                new_post = Post(
                    author=bot_user,
                    content=f"The energy in {league.name} is insane! 🔥 #Sports #Shorts",
                    post_type='video',
                    league=league,
                    team=bot_user.favorite_team if bot_user.favorite_team else None,
                    is_short=True
                )

                # 6. Save directly to the FileField
                # Wrap the raw content in ContentFile to trigger the GoogleCloudStorage backend
                self.stdout.write(f"📤 Uploading to Firebase...")
                new_post.media_file.save(
                    file_path, 
                    ContentFile(vid_res.content), 
                    save=True
                )

                # 7. Add Hashtags
                tags = [league.name.replace(" ", ""), "Shorts", "ConnectDial"]
                for t in tags:
                    tag_obj, _ = Hashtag.objects.get_or_create(name=t)
                    new_post.hashtags.add(tag_obj)

                self.stdout.write(self.style.SUCCESS(f"✅ Post LIVE: {new_post.media_file.url}"))
            else:
                self.stdout.write(self.style.ERROR(f"❌ Pexels download failed (Status: {vid_res.status_code})"))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Script Error: {str(e)}"))