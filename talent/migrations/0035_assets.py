from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

def asset_upload(instance, filename):
    return f"assets/{filename}"


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("talent", "0034_bookmark"),
    ]

    operations = [
        migrations.AddField(
            model_name="supportaccess",
            name="assets",
            field=models.BooleanField(default=False, verbose_name="اموال"),
        ),
        migrations.CreateModel(
            name="AssetGroup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=80, unique=True, verbose_name="نام دسته")),
                ("note", models.CharField(blank=True, max_length=200, verbose_name="توضیح")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "دسته اموال",
                "verbose_name_plural": "دسته‌های اموال",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="Asset",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, verbose_name="نام مال")),
                ("number", models.CharField(max_length=40, unique=True, verbose_name="شماره اموال")),
                ("serial", models.CharField(blank=True, max_length=80, verbose_name="شماره سریال")),
                ("brand", models.CharField(blank=True, max_length=120, verbose_name="برند و مدل")),
                ("location", models.CharField(blank=True, max_length=120, verbose_name="محل نگهداری")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("in_use", "تحویل شده"),
                            ("stock", "در انبار"),
                            ("repair", "در تعمیر"),
                            ("lost", "مفقود"),
                            ("retired", "اسقاط"),
                        ],
                        default="stock",
                        max_length=20,
                        verbose_name="وضعیت",
                    ),
                ),
                ("image", models.ImageField(blank=True, upload_to=asset_upload, verbose_name="عکس")),
                ("purchase_date", models.DateField(blank=True, null=True, verbose_name="تاریخ خرید")),
                ("price", models.PositiveBigIntegerField(blank=True, null=True, verbose_name="قیمت خرید (تومان)")),
                ("holder_name", models.CharField(blank=True, max_length=120, verbose_name="تحویل‌گیرنده")),
                ("holder_phone", models.CharField(blank=True, max_length=20, verbose_name="شماره تحویل‌گیرنده")),
                ("holder_unit", models.CharField(blank=True, max_length=120, verbose_name="واحد یا سمت")),
                ("handed_at", models.DateField(blank=True, null=True, verbose_name="تاریخ تحویل")),
                ("note", models.TextField(blank=True, verbose_name="توضیح")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="assets_created",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="ثبت‌کننده",
                    ),
                ),
                (
                    "group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="assets",
                        to="talent.assetgroup",
                        verbose_name="دسته",
                    ),
                ),
            ],
            options={
                "verbose_name": "مال",
                "verbose_name_plural": "اموال",
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.CreateModel(
            name="AssetHandover",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("holder_name", models.CharField(max_length=120, verbose_name="تحویل‌گیرنده")),
                ("holder_phone", models.CharField(blank=True, max_length=20, verbose_name="شماره")),
                ("holder_unit", models.CharField(blank=True, max_length=120, verbose_name="واحد یا سمت")),
                ("handed_at", models.DateField(verbose_name="تاریخ تحویل")),
                ("returned_at", models.DateField(blank=True, null=True, verbose_name="تاریخ بازگشت")),
                ("note", models.CharField(blank=True, max_length=200, verbose_name="توضیح")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "asset",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="handovers",
                        to="talent.asset",
                        verbose_name="مال",
                    ),
                ),
                (
                    "recorded_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="asset_handovers",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="ثبت‌کننده",
                    ),
                ),
            ],
            options={
                "verbose_name": "تحویل مال",
                "verbose_name_plural": "تحویل‌های اموال",
                "ordering": ["-handed_at", "-id"],
            },
        ),
    ]
