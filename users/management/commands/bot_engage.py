import random
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from posts.models import Post, PostLike, Comment
from django.utils import timezone

User = get_user_model()

class Command(BaseCommand):
    help = 'Forces bots to interact ONLY with leagues they follow'

    def handle(self, *args, **options):
        # 1. Get posts from the last 24 hours
        recent_posts = Post.objects.filter(
            created_at__gte=timezone.now() - timezone.timedelta(hours=24)
        )

        if not recent_posts.exists():
            self.stdout.write("No recent posts found.")
            return

        for post in recent_posts:
            # 2. MATCHING LOGIC: Find fans of this specific league
            # We filter by the league mandatory, and team if the post has one
            eligible_bots = User.objects.filter(
                profile__is_bot=True,
                favorite_league=post.league
            ).exclude(id=post.author.id)

            if not eligible_bots.exists():
                continue

            # 3. FIX: Changed 'order_size' to 'order_by'
            num_engagers = random.randint(1, 2)
            participants = eligible_bots.order_by('?')[:num_engagers]

            for bot in participants:
                # Check if they already liked it to avoid duplicates
                if PostLike.objects.filter(user=bot, post=post).exists():
                    continue

                action = random.choice(['like', 'comment', 'repost'])

                if action == 'like':
                    PostLike.objects.get_or_create(user=bot, post=post)
                    self.stdout.write(f"❤️ {bot.username} (Fan of {post.league.name}) liked a post.")

                elif action == 'comment':
                    # Use the post's team name if available, otherwise league name
                    subject = post.team.name if post.team else post.league.name
                    comments = [
                        f"Big moves for {subject}! 🔥",
                        "This is exactly what the league needed.",
                        "Finally some real updates. ConnectDial is the place to be!",
                        f"Watching {subject} closely this season. Great post!"
                    ]
                    Comment.objects.create(user=bot, post=post, content=random.choice(comments))
                    self.stdout.write(f"💬 {bot.username} commented on a {post.league.name} post.")

                elif action == 'repost':
                    # Ensure the repost carries the league and team ID
                    Post.objects.create(
                        author=bot,
                        content=f"You guys need to see this! #{post.league.name.replace(' ', '')}",
                        post_type='text',
                        league=post.league,
                        team=post.team,
                        parent_post=post,
                        is_repost=True
                    )
                    self.stdout.write(f"🔄 {bot.username} shared a {post.league.name} update.")

        self.stdout.write(self.style.SUCCESS("✅ Targeted engagement complete!"))