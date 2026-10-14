from django.conf import settings
from django.db import migrations, models


def keep_only_manager(apps, schema_editor):
    User = apps.get_model("auth", "User")
    Profile = apps.get_model("talent", "Profile")
    admin_phone = "09124770435"
    chosen_id = None
    for profile in Profile.objects.filter(phone=admin_phone).order_by("id"):
        user = User.objects.filter(pk=profile.user_id).first()
        if user is None:
            continue
        if chosen_id is None or user.is_staff:
            chosen_id = user.pk
            if user.is_staff:
                break
    if chosen_id is None:
        staff = User.objects.filter(is_staff=True).order_by("id").first()
        if staff is not None:
            chosen_id = staff.pk
    if chosen_id is None:
        return
    User.objects.exclude(pk=chosen_id).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("talent", "0007_two_lines_per_phone"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="archived_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="بایگانی"),
        ),
        migrations.RunPython(keep_only_manager, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="profile",
            constraint=models.UniqueConstraint(
                condition=models.Q(("phone", ""), _negated=True),
                fields=("phone",),
                name="unique_profile_phone",
            ),
        ),
    ]
