from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from talent.models import ChargeRequest, Profile, ProfileRole, Wallet, WalletEntry


def toman(amount):
    return f"{int(amount):,}".replace(",", "٬")


def year_price():
    return settings.ACCOUNT_YEAR_PRICE


def wallet_for(user):
    wallet, _ = Wallet.objects.get_or_create(user=user)
    return wallet


def public_profiles():
    return (
        Profile.objects.filter(
            account_status="approved",
            archived_at__isnull=True,
            user__is_active=True,
            role_links__status=ProfileRole.Status.APPROVED,
        )
        .exclude(user__is_staff=True)
        .distinct()
    )


def viewer_can_open(user, profile):
    if user.is_authenticated and (user.id == profile.user_id or user.is_staff):
        return True
    return profile.is_public()


def buy_year(user):
    price = year_price()
    with transaction.atomic():
        wallet, _ = Wallet.objects.select_for_update().get_or_create(user=user)
        if wallet.balance < price:
            return False
        wallet.balance -= price
        wallet.save(update_fields=["balance"])
        WalletEntry.objects.create(
            wallet=wallet,
            amount=-price,
            kind=WalletEntry.Kind.PURCHASE,
            note="خرید یک سال نمایش صفحه",
        )
        profile = Profile.objects.select_for_update().get(user=user)
        start = timezone.now()
        if profile.listed_until and profile.listed_until > start:
            start = profile.listed_until
        profile.listed_until = start + timedelta(days=365)
        profile.save(update_fields=["listed_until"])
    return True


def approve_charge(charge_id):
    with transaction.atomic():
        item = (
            ChargeRequest.objects.select_for_update()
            .filter(pk=charge_id, status=ChargeRequest.Status.PENDING)
            .first()
        )
        if item is None:
            return False
        wallet, _ = Wallet.objects.select_for_update().get_or_create(user=item.user)
        wallet.balance += item.amount
        wallet.save(update_fields=["balance"])
        WalletEntry.objects.create(
            wallet=wallet,
            amount=item.amount,
            kind=WalletEntry.Kind.CHARGE,
            note="شارژ تاییدشده",
        )
        item.status = ChargeRequest.Status.APPROVED
        item.reviewed_at = timezone.now()
        item.save(update_fields=["status", "reviewed_at"])
    return True
