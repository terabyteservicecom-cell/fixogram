from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from talent.models import Profile, Wallet


@receiver(post_save, sender=get_user_model())
def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(
            user=instance,
            defaults={"display_name": instance.get_full_name() or instance.username},
        )
        Wallet.objects.get_or_create(user=instance)
