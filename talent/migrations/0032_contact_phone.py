from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("talent", "0031_visit_file"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="contact_phone",
            field=models.CharField(blank=True, max_length=20, verbose_name="شماره تماس نمایشی"),
        ),
    ]
