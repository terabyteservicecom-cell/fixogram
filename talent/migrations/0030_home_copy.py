from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("talent", "0029_seo_sections"),
    ]

    operations = [
        migrations.CreateModel(
            name="HomeCopy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("eyebrow", models.CharField(blank=True, max_length=80, verbose_name="برچسب بالای عنوان")),
                ("headline", models.CharField(blank=True, max_length=200, verbose_name="عنوان اصلی")),
                ("lead", models.TextField(blank=True, verbose_name="توضیح زیر عنوان")),
                ("section_link", models.CharField(blank=True, max_length=80, verbose_name="متن لینک بخش")),
                ("empty_people", models.CharField(blank=True, max_length=200, verbose_name="وقتی متخصصی نیست")),
                ("jobs_title", models.CharField(blank=True, max_length=80, verbose_name="عنوان استخدام")),
                ("jobs_lead", models.TextField(blank=True, verbose_name="توضیح استخدام")),
                ("empty_jobs", models.CharField(blank=True, max_length=200, verbose_name="وقتی آگهی نیست")),
                ("jobs_button", models.CharField(blank=True, max_length=80, verbose_name="دکمه آگهی‌ها")),
                ("footer", models.TextField(blank=True, verbose_name="متن پایین صفحه")),
            ],
            options={
                "verbose_name": "نوشته صفحه اصلی",
                "verbose_name_plural": "نوشته‌های صفحه اصلی",
            },
        ),
    ]
