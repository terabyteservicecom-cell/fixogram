from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("talent", "0021_blog_comments"),
    ]

    operations = [
        migrations.AddField(
            model_name="welcomemessage",
            name="is_active",
            field=models.BooleanField(default=True, verbose_name="روشن"),
        ),
    ]
