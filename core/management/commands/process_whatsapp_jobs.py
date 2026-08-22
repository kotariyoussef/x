"""Django management command to process pending WhatsApp group message delivery jobs."""
from django.core.management.base import BaseCommand
from core.services.group_automation import process_all_pending_jobs


class Command(BaseCommand):
    help = "Processes pending WhatsApp group message delivery jobs in a serialized, rate-limited queue."

    def add_arguments(self, parser):
        parser.add_argument(
            '--max-jobs',
            type=int,
            default=20,
            help='Maximum number of jobs to process in this execution run (default: 20)'
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=1.0,
            help='Delay in seconds between consecutive group sends (default: 1.0)'
        )

    def handle(self, *args, **options):
        max_jobs = options['max_jobs']
        delay = options['delay']
        self.stdout.write(f"Starting WhatsApp group jobs processor (max_jobs={max_jobs}, delay={delay}s)...")
        
        count = process_all_pending_jobs(max_jobs=max_jobs, delay_between_sends=delay)
        
        if count > 0:
            self.stdout.write(self.style.SUCCESS(f"Successfully processed {count} WhatsApp job(s)."))
        else:
            self.stdout.write("No pending WhatsApp jobs to process.")
