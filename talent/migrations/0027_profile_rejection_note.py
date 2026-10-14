from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("talent", "0026_push_subscription"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="rejection_note",
            field=models.TextField(blank=True, verbose_name="دلیل رد"),
        ),
    ]
