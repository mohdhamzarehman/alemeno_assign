from django.core.management.base import BaseCommand

from credit.tasks import ingest_initial_data


class Command(BaseCommand):
    help = "Enqueue background ingestion of initial Excel datasets."

    def handle(self, *args, **options):
        ingest_initial_data.delay()
        self.stdout.write(self.style.SUCCESS("Ingestion task queued."))
