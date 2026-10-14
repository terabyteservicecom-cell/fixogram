from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("talent", "0023_support_access"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="is_visitor",
            field=models.BooleanField(default=False, verbose_name="ویزیتور"),
        ),
        migrations.AddField(
            model_name="profile",
            name="recruited_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="recruits",
                to="talent.profile",
                verbose_name="ویزیتور پذیرنده",
            ),
        ),
    ]
