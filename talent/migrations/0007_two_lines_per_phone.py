from django.db import migrations


def drop_single_phone_limit(apps, schema_editor):
    schema_editor.execute('DROP INDEX IF EXISTS "unique_profile_phone"')


class Migration(migrations.Migration):

    dependencies = [
        ("talent", "0006_welcome_message"),
    ]

    operations = [
        migrations.RunPython(drop_single_phone_limit, migrations.RunPython.noop),
    ]
