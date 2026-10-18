from django.db import migrations, models


def _canonical(raw):
    persian = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    phone = "".join(ch for ch in (raw or "").translate(persian) if ch.isdigit() or ch == "+")
    if phone.startswith("+98"):
        phone = "0" + phone[3:]
    elif phone.startswith("0098"):
        phone = "0" + phone[4:]
    elif phone.startswith("98") and len(phone) == 12:
        phone = "0" + phone[2:]
    if len(phone) == 10 and phone.startswith("9"):
        phone = "0" + phone
    return phone if len(phone) == 11 and phone.startswith("09") else ""


def normalize_and_dedupe(apps, schema_editor):
    Profile = apps.get_model("talent", "Profile")
    User = apps.get_model("auth", "User")
    by_phone = {}
    for profile in Profile.objects.exclude(phone="").select_related("user").order_by("id"):
        phone = _canonical(profile.phone)
        if not phone:
            continue
        if profile.phone != phone:
            profile.phone = phone
            profile.save(update_fields=["phone"])
        by_phone.setdefault(phone, []).append(profile)
    for phone, rows in by_phone.items():
        if len(rows) < 2:
            continue
        keeper = rows[0]
        for profile in rows[1:]:
            user = profile.user
            profile.phone = ""
            profile.archived_at = profile.archived_at or profile.created_at
            profile.save(update_fields=["phone", "archived_at"])
            if user is None:
                continue
            user.is_active = False
            if user.username == phone or user.username.startswith(phone):
                user.username = f"dup-{user.pk}-{phone[-4:]}"
            user.save(update_fields=["is_active", "username"])
            # keeper already has the phone; skip unused var warning
            _ = keeper


class Migration(migrations.Migration):

    dependencies = [
        ("talent", "0037_post_cover"),
    ]

    operations = [
        migrations.RunPython(normalize_and_dedupe, migrations.RunPython.noop),
        migrations.RunSQL(
            sql='CREATE UNIQUE INDEX IF NOT EXISTS "unique_profile_phone" ON "talent_profile" ("phone") WHERE NOT ("phone" = \'\')',
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
