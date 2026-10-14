from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("talent", "0035_assets"),
    ]

    operations = [
        migrations.DeleteModel(name="AssetHandover"),
        migrations.DeleteModel(name="Asset"),
        migrations.DeleteModel(name="AssetGroup"),
        migrations.RemoveField(model_name="supportaccess", name="assets"),
    ]
