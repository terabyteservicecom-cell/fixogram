from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("talent", "0022_announcement_switch"),
    ]

    operations = [
        migrations.CreateModel(
            name="SupportAccess",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("moderate", models.BooleanField(default=False, verbose_name="صف تایید")),
                ("categories", models.BooleanField(default=False, verbose_name="دسته‌ها")),
                ("banners", models.BooleanField(default=False, verbose_name="بنرها")),
                ("blog", models.BooleanField(default=False, verbose_name="بلاگ")),
                ("broadcast", models.BooleanField(default=False, verbose_name="پیام گروهی")),
                ("tickets", models.BooleanField(default=False, verbose_name="تیکت و تخلف")),
                ("reports", models.BooleanField(default=False, verbose_name="گزارشات")),
                (
                    "profile",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="access",
                        to="talent.profile",
                        verbose_name="پشتیبان",
                    ),
                ),
            ],
            options={
                "verbose_name": "دسترسی پشتیبان",
                "verbose_name_plural": "دسترسی پشتیبان‌ها",
            },
        ),
        migrations.CreateModel(
            name="StaffLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("path", models.CharField(max_length=200, verbose_name="مسیر")),
                ("summary", models.CharField(max_length=200, verbose_name="کار")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="staff_logs",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="پشتیبان",
                    ),
                ),
            ],
            options={
                "verbose_name": "لاگ پشتیبان",
                "verbose_name_plural": "لاگ پشتیبان‌ها",
                "ordering": ["-created_at"],
            },
        ),
    ]
