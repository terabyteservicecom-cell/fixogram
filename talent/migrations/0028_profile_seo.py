from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("talent", "0027_profile_rejection_note"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="seo_title",
            field=models.CharField(blank=True, max_length=70, verbose_name="عنوان گوگل"),
        ),
        migrations.AddField(
            model_name="profile",
            name="seo_description",
            field=models.CharField(blank=True, max_length=170, verbose_name="توضیح گوگل"),
        ),
    ]
