from django.db import migrations, models

import talent.private_storage


class Migration(migrations.Migration):

    dependencies = [
        ("talent", "0030_home_copy"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="visit_file",
            field=models.FileField(
                blank=True,
                max_length=240,
                storage=talent.private_storage.IdentityStorage(),
                upload_to="visits/%Y/%m/",
                verbose_name="فایل پذیرش",
            ),
        ),
    ]
