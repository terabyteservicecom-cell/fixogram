from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("talent", "0032_contact_phone"),
    ]

    operations = [
        migrations.AddField(
            model_name="homecopy",
            name="job_warning",
            field=models.TextField(blank=True, verbose_name="زنگ خطر قبل از همکاری"),
        ),
        migrations.AddField(
            model_name="violationreport",
            name="job",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="violation_reports",
                to="talent.jobpost",
                verbose_name="آگهی",
            ),
        ),
    ]
