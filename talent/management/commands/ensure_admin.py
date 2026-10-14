import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from talent.forms import accounts_for_phone
from talent.models import Profile


class Command(BaseCommand):
    help = "شماره مدیر را تنها حساب مدیریت می‌کند."

    def handle(self, *args, **options):
        phone = settings.ADMIN_PHONE
        User = get_user_model()
        managers = accounts_for_phone(phone)
        if not managers:
            username = os.environ.get("ADMIN_USERNAME", phone).strip() or phone
            user = User.objects.filter(username=username).first() or User.objects.filter(username=phone).first()
            if user is None:
                user = User(username=phone)
                user.save()
            profile = Profile.objects.filter(user=user).first()
            if profile is None:
                profile = Profile(user=user, display_name="مدیر سیستم", phone=phone)
            elif not profile.phone:
                profile.phone = phone
                if not profile.display_name:
                    profile.display_name = "مدیر سیستم"
            profile.account_status = "approved"
            profile.save()
            managers = accounts_for_phone(phone) or [user]
        kept = []
        for user in managers:
            user.is_staff = True
            user.is_superuser = True
            password = os.environ.get("ADMIN_PASSWORD", "").strip()
            if password:
                user.set_password(password)
            elif user.check_password("1111") or not user.has_usable_password():
                user.set_unusable_password()
            user.save()
            profile = Profile.objects.filter(user=user).first()
            if profile is not None and profile.account_status != "approved":
                profile.account_status = "approved"
                profile.save(update_fields=["account_status"])
            kept.append(user.pk)
        support_ids = list(
            Profile.objects.filter(is_support=True).exclude(user_id__in=kept).values_list("user_id", flat=True)
        )
        User.objects.filter(is_superuser=True).exclude(pk__in=kept).update(is_superuser=False)
        User.objects.filter(is_staff=True).exclude(pk__in=kept + support_ids).update(is_staff=False)
        self.stdout.write(self.style.SUCCESS("admin phone is ready"))
