from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import User, Profile


@receiver(post_save, sender=User)
def sync_user_profile(sender, instance, created, **kwargs):
    """
    Auto-create a Profile on first save; keep it in sync on subsequent saves.

    FIX: The old code used two separate signal handlers — create_user_profile
    and save_user_profile — which caused a redundant double-write on user
    creation (get_or_create → profile saved, then save() → profile saved again).
    Merging into one handler eliminates the double-write.
    """
    if created:
        Profile.objects.get_or_create(user=instance)
    else:
        try:
            instance.profile.save()
        except Profile.DoesNotExist:
            Profile.objects.create(user=instance)