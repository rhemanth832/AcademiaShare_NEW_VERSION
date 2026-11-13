from django.core.management.base import BaseCommand
from core.exams import finalize_expired

class Command(BaseCommand):
    help = 'Finalize timed-out exams using saved answers. Suitable for a once-per-minute scheduled job.'
    def handle(self, *args, **options):
        finalize_expired()
        self.stdout.write('Expired exam attempts finalized.')
