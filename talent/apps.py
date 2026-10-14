from django.apps import AppConfig


class TalentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "talent"
    verbose_name = "فیکسوگرام"

    def ready(self):
        from talent import signals  # noqa: F401
