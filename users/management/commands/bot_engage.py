import random
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from posts.models import Post, PostLike, Comment
from django.utils import timezone

User = get_user_model()

class Command(BaseCommand):
    help = 'Bots interact intelligently with posts based on content analysis'

    def get_intelligent_response(self, content, subject):
        """Analyzes post content to return a contextual response."""
        content = content.lower()
        
        # 1. Reaction Pools
        reactions = {
            "praise": [
                f"Absolute class from {subject}! 🔥",
                f"This is why we love {subject}. What a moment!",
                f"Incredible performance by {subject}. Top tier!",
                f"The standard is being set by {subject} today. 👏"
            ],
            "excitement": [
                f"The atmosphere for {subject} must be insane right now!",
                "I'm literally on the edge of my seat watching this! 🍿",
                f"Big moves! {subject} is cooking something special this season.",
                f"Can't wait to see how this plays out for {subject}!"
            ],
            "analysis": [
                f"Stats don't lie, {subject} is dominating the play right now.",
                "Tactically, this is a masterpiece.",
                f"Interesting perspective on {subject}. Hadn't thought of it that way.",
                f"This changes everything for the {subject} standings."
            ],
            "generic": [
                f"Great update on {subject}. Thanks for sharing!",
                f"Always keeping an eye on {subject}. #ConnectDial",
                "Quality content. This is exactly why I joined ConnectDial.",
                "Keep these updates coming! 📈"
            ]
        }

        # 2. Keyword Matching Logic
        if any(word in content for word in ["win", "goal", "champion", "amazing", "great", "fire", "win"]):
            category = "praise"
        elif any(word in content for word in ["breaking", "news", "official", "signed", "contract", "update"]):
            category = "excitement"
        elif any(word in content for word in ["stats", "analysis", "tactics", "think", "review", "history"]):
            category = "analysis"
        else:
            category = "generic"

        return random.choice(reactions[category])

    def handle(self, *args, **options):
        # 1. LIMIT: Only pick 10-15 random recent posts to prevent "spamming" the feed
        recent_posts = Post.objects.filter(
            created_at__gte=timezone.now() - timezone.timedelta(hours=24)
        ).order_by('?')[:15]

        if not recent_posts.exists():
            self.stdout.write("No recent posts found.")
            return

        for post in recent_posts:
            # 2. MATCHING LOGIC: Find bots that follow this specific league
            eligible_bots = User.objects.filter(
                profile__is_bot=True,
                favorite_league=post.league
            ).exclude(id=post.author.id)

            if not eligible_bots.exists():
                continue

            # 3. SELECT PARTICIPANTS: 1 or 2 bots per post
            num_engagers = random.randint(1, 2)
            participants = eligible_bots.order_by('?')[:num_engagers]

            for bot in participants:
                # 4. AVOID DUPLICATES: Don't interact with the same post twice
                if PostLike.objects.filter(user=bot, post=post).exists() or \
                   Comment.objects.filter(user=bot, post=post).exists():
                    continue

                action = random.choice(['like', 'comment', 'repost'])
                subject = post.team.name if post.team else post.league.name

                if action == 'like':
                    PostLike.objects.get_or_create(user=bot, post=post)
                    self.stdout.write(f"❤️ {bot.username} liked a {subject} post.")

                elif action == 'comment':
                    content = self.get_intelligent_response(post.content, subject)
                    Comment.objects.create(user=bot, post=post, content=content)
                    self.stdout.write(f"💬 {bot.username}: {content}")

                elif action == 'repost':
                    # 5. AVOID REPOST SPAM: Check if this bot already reposted THIS specific post
                    if Post.objects.filter(author=bot, parent_post=post, is_repost=True).exists():
                        continue

                    repost_quotes = [
                        f"If you're following {post.league.name}, you need to see this update on {subject}.",
                        f"Huge news regarding {subject}. Keeping my eyes on this! 👇",
                        f"This is a massive development for {subject}. Worth a share!",
                        f"Directly from the source. Great news for the {subject} fans.",
                        f"ConnectDial always has the fastest updates on {subject}. Check this out!"
                    ]

                    Post.objects.create(
                        author=bot,
                        content=random.choice(repost_quotes),
                        post_type='text',
                        league=post.league,
                        team=post.team,
                        parent_post=post,
                        is_repost=True
                    )
                    self.stdout.write(f"🔄 {bot.username} shared a {subject} update.")

        self.stdout.write(self.style.SUCCESS("✅ Intelligent engagement complete!"))