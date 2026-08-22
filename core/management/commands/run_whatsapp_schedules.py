"""Django management command to execute scheduled WhatsApp automations."""
from datetime import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import WhatsAppAutomation
from core.services.group_automation import trigger_automation


class Command(BaseCommand):
    help = "Evaluates and triggers scheduled WhatsApp automations."

    def handle(self, *args, **options):
        now = timezone.now()
        self.stdout.write(f"Evaluating scheduled WhatsApp automations at {now.isoformat()}...")

        scheduled_automations = WhatsAppAutomation.objects.filter(
            enabled=True,
            trigger='SCHEDULED'
        ).select_related('template')

        triggered_count = 0

        for auto in scheduled_automations:
            # Check if next_run_at is reached or not set
            if auto.next_run_at and auto.next_run_at > now:
                continue

            self.stdout.write(f"Executing scheduled automation: '{auto.name}'")
            context = {
                'now': now.strftime('%d/%m/%Y %H:%M'),
                'date': now.strftime('%d/%m/%Y'),
                'time': now.strftime('%H:%M'),
            }
            results = trigger_automation(
                trigger_name='SCHEDULED',
                context=context,
                source_event_id=f"schedule_{auto.pk}_{now.strftime('%Y%m%d%H%M')}",
            )
            triggered_count += len(results)

        self.stdout.write(self.style.SUCCESS(f"Finished evaluating schedules. Triggered {triggered_count} automation(s)."))
