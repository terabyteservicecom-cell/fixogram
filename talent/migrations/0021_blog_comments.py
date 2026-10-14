from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("talent", "0020_job_listing_duration"),
    ]

    operations = [
        migrations.CreateModel(
            name="PostComment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("score", models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="امتیاز")),
                ("body", models.TextField(blank=True, verbose_name="نظر")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "author",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="post_comments",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="نویسنده نظر",
                    ),
                ),
                (
                    "post",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="comments",
                        to="talent.post",
                        verbose_name="نوشته",
                    ),
                ),
            ],
            options={
                "verbose_name": "نظر بلاگ",
                "verbose_name_plural": "نظرهای بلاگ",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="postcomment",
            constraint=models.UniqueConstraint(fields=("post", "author"), name="unique_post_comment"),
        ),
    ]
