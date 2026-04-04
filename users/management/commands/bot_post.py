import random
import requests
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from posts.models import Post, Hashtag
from leagues.models import League, Team

User = get_user_model()

class Command(BaseCommand):
    help = 'Fetches LIVE sports news and makes a bot post it'

    def add_arguments(self, parser):
        parser.add_argument('league_name', type=str)

    def handle(self, *args, **options):
        league_query = options['league_name']
        API_KEY = "b6c80809d3904036baa2e07657c02831" 
        
        # 1. Get League and a Random Team within it
        league = League.objects.filter(name__icontains=league_query).first()
        if not league:
            self.stdout.write(self.style.ERROR(f"League '{league_query}' not found."))
            return
        
        teams = list(Team.objects.filter(league=league))
        target_team = random.choice(teams) if teams else None

        # 2. Find or "Recruit" a Bot
        # If no one likes this league yet, we'll force a random bot to become a fan
        bot_user = User.objects.filter(profile__is_bot=True, favorite_league=league).order_by('?').first()
        
        if not bot_user:
            bot_user = User.objects.filter(profile__is_bot=True).order_by('?').first()
            if bot_user:
                bot_user.favorite_league = league
                bot_user.favorite_team = target_team
                bot_user.save()
                self.stdout.write(self.style.SUCCESS(f"Recruited {bot_user.username} to follow {league.name}"))
            else:
                self.stdout.write(self.style.ERROR("No bots found. Run generate_bots first!"))
                return

        # 3. Fetch Real News from NewsAPI
        self.stdout.write(f"Fetching live updates for {league.name}...")
        # Searching for the league name + "sports" to keep it relevant
        url = f"https://newsapi.org/v2/everything?q={league.name}%20sports&sortBy=publishedAt&language=en&apiKey={API_KEY}"
        
        try:
            response = requests.get(url).json()
            articles = response.get('articles', [])
            
            if not articles:
                self.stdout.write(self.style.WARNING("No live news found. Using template."))
                content = f"Can't wait for the next {league.name} match! Who's with me? 🔥"
                image_url = None
            else:
                # Pick a random article from the top 10 recent ones
                article = random.choice(articles[:10])
                title = article['title']
                desc = article['description'] if article['description'] else ""
                source = article['source']['name']
                content = f"{title}\n\n{desc}\n\n(Source: {source})"
                image_url = article.get('urlToImage')

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"News fetch failed: {e}"))
            return

        # 4. Create the Post
        new_post = Post.objects.create(
            author=bot_user,
            content=content,
            post_type='image' if image_url else 'text',
            league=league,
            team=target_team,
            is_short=False
        )

        # 5. Attach Media if available
        if image_url:
            try:
                img_res = requests.get(image_url, timeout=5)
                if img_res.status_code == 200:
                    new_post.media_file.save(f"news_{new_post.id}.jpg", ContentFile(img_res.content), save=True)
            except:
                pass

        # 6. Add Hashtags (e.g., #NBA #Sports #ConnectDial)
        tags = ["Sports", league.name.replace(" ", ""), "ConnectDial"]
        for t in tags:
            tag_obj, _ = Hashtag.objects.get_or_create(name=t)
            new_post.hashtags.add(tag_obj)

        self.stdout.write(self.style.SUCCESS(f"✅ Live Post by {bot_user.username} for {league.name}!"))