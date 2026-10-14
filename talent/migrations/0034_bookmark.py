from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("talent", "0033_job_warning_and_report"),
    ]

    operations = [
        migrations.CreateModel(
            name="Bookmark",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("section", "بخش"), ("profile", "متخصص"), ("job", "آگهی"), ("post", "نوشته")], max_length=20, verbose_name="نوع")),
                ("object_id", models.PositiveIntegerField(verbose_name="شناسه")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bookmarks",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="کاربر",
                    ),
                ),
            ],
            options={
                "verbose_name": "ذخیره",
                "verbose_name_plural": "ذخیره‌ها",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="bookmark",
            constraint=models.UniqueConstraint(fields=("user", "kind", "object_id"), name="unique_bookmark"),
        ),
    ]
