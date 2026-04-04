import random
import time
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from users.models import Follow

User = get_user_model()

class Command(BaseCommand):
    help = 'Makes bots follow users (real and bots) who share their sports interests'

    def handle(self, *args, **options):
        # 1. Get all active bots
        bots = User.objects.filter(profile__is_bot=True)
        
        if not bots.exists():
            self.stdout.write(self.style.ERROR("No bots found. Run generate_bots first."))
            return

        self.stdout.write(f"👥 Syncing the social graph for {bots.count()} bots...")

        for bot in bots:
            # 2. TARGETING: Find users who share the same favorite_league or favorite_team
            # We prioritize team-mates first, then league-mates
            target_users = User.objects.filter(
                favorite_league=bot.favorite_league
            ).exclude(id=bot.id)

            if not target_users.exists():
                continue

            # 3. Pick 1-3 random users to follow
            num_to_follow = random.randint(1, 3)
            to_follow_list = target_users.order_by('?')[:num_to_follow]

            for target in to_follow_list:
                # 4. Use your Follow model's logic
                # We use get_or_create to satisfy your 'unique_together' constraint
                follow_obj, created = Follow.objects.get_or_create(
                    follower=bot,
                    followed=target
                )

                if created:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  ✨ {bot.username} (Fan of {bot.favorite_league.name}) "
                            f"is now following {target.username}"
                        )
                    )
                else:
                    self.stdout.write(f"  - {bot.username} already follows {target.username}")

            # Small delay to prevent database locking on your HP 290
            time.sleep(0.2)

        self.stdout.write(self.style.SUCCESS("✅ Social graph expansion complete!"))


        