from django.core.management.base import BaseCommand
from core.models import Level

class Command(BaseCommand):
    help = 'Create default academic levels for Primaire, Collège, and Lycée'

    def handle(self, *args, **options):
        levels_data = [
            # Garderie
            ('Petite Section (PS)', 'GARDERIE'),
            ('Moyenne Section (MS)', 'GARDERIE'),
            ('Grande Section (GS)', 'GARDERIE'),
            # Primaire
            ('1AP', 'PRIMAIRE'),
            ('2AP', 'PRIMAIRE'),
            ('3AP', 'PRIMAIRE'),
            ('4AP', 'PRIMAIRE'),
            ('5AP', 'PRIMAIRE'),
            ('6AP', 'PRIMAIRE'),
            # Collège
            ('1ASC', 'COLLEGE'),
            ('2ASC', 'COLLEGE'),
            ('3ASC', 'COLLEGE'),
            # Lycée
            ('Tronc Commun (TC)', 'LYCEE'),
            ('1ère année Bac (1Bac)', 'LYCEE'),
            ('2ème année Bac (2Bac)', 'LYCEE'),
        ]

        self.stdout.write(self.style.NOTICE('Setting up default academic levels...'))
        for name, category in levels_data:
            level, created = Level.objects.get_or_create(
                name=name,
                defaults={'category': category}
            )
            if not created and level.category != category:
                level.category = category
                level.save()
                self.stdout.write(self.style.SUCCESS(f'Updated level: {name} ({category})'))
            elif created:
                self.stdout.write(self.style.SUCCESS(f'Created level: {name} ({category})'))
            else:
                self.stdout.write(f'Level already exists: {name} ({category})')
        self.stdout.write(self.style.SUCCESS('Default levels set up successfully!'))
