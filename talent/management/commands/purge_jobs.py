from django.core.management.base import BaseCommand

from talent.models import JobPost


class Command(BaseCommand):
    help = "آگهی‌هایی که مدتشان تمام شده را حذف می‌کند."

    def handle(self, *args, **options):
        JobPost.purge_expired()
        self.stdout.write("آگهی‌های منقضی حذف شدند.")
