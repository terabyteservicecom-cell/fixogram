from django.core.management.base import BaseCommand

from talent.catalog import seed_catalog


class Command(BaseCommand):
    help = "عنوان‌های سینما و تلویزیون را می‌سازد."

    def handle(self, *args, **options):
        seed_catalog()
        self.stdout.write(self.style.SUCCESS("roles ready"))
