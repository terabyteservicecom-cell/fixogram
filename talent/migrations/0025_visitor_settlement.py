from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("talent", "0024_visitor_recruiting"),
    ]

    operations = [
        migrations.CreateModel(
            name="VisitorSettlement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.CharField(blank=True, max_length=40, verbose_name="مبلغ")),
                ("note", models.TextField(blank=True, verbose_name="شرح")),
                ("recruit_count", models.PositiveIntegerField(default=0, verbose_name="تعداد تسویه‌شده")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "visitor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="settlements",
                        to="talent.profile",
                        verbose_name="ویزیتور",
                    ),
                ),
            ],
            options={
                "verbose_name": "تسویه ویزیتور",
                "verbose_name_plural": "تسویه‌های ویزیتور",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddField(
            model_name="profile",
            name="settlement",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="covered_recruits",
                to="talent.visitorsettlement",
                verbose_name="تسویه",
            ),
        ),
    ]
