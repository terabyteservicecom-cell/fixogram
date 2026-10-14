from datetime import timedelta

from django.db import migrations
from django.utils import timezone


def publish_funded_profiles(apps, schema_editor):
    Profile = apps.get_model("talent", "Profile")
    Wallet = apps.get_model("talent", "Wallet")
    WalletEntry = apps.get_model("talent", "WalletEntry")
    price = 100_000
    now = timezone.now()
    for wallet in Wallet.objects.filter(balance__gte=price):
        profile = Profile.objects.filter(user_id=wallet.user_id).first()
        if profile is None:
            continue
        if profile.archived_at or (profile.listed_until and profile.listed_until > now):
            continue
        wallet.balance -= price
        wallet.save(update_fields=["balance"])
        WalletEntry.objects.create(
            wallet_id=wallet.pk,
            amount=-price,
            kind="purchase",
            note="خرید یک سال نمایش صفحه",
        )
        profile.listed_until = now + timedelta(days=365)
        profile.save(update_fields=["listed_until"])


class Migration(migrations.Migration):

    dependencies = [
        ("talent", "0008_one_phone_and_archive"),
    ]

    operations = [
        migrations.RunPython(publish_funded_profiles, migrations.RunPython.noop),
    ]
