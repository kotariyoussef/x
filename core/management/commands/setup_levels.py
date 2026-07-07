from django.core.management.base import BaseCommand
from core.models import Level, LevelCategory

class Command(BaseCommand):
    help = 'Create default academic levels for Garderie, Primaire, Collège, and Lycée'

    CATEGORIES = [
        ('GARDERIE', 'La Garderie'),
        ('PRIMAIRE', 'Primaire'),
        ('COLLEGE', 'Collège'),
        ('LYCEE', 'Lycée'),
    ]

    LEVELS_DATA = [
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

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE('Setting up default academic levels...'))

        # Create or fetch LevelCategory objects
        category_map = {}
        for code, name in self.CATEGORIES:
            cat, _ = LevelCategory.objects.get_or_create(code=code, defaults={'name': name})
            category_map[code] = cat

        for name, category_code in self.LEVELS_DATA:
            cat = category_map[category_code]
            level, created = Level.objects.get_or_create(
                name=name,
                defaults={'category': cat}
            )
            if not created and level.category != cat:
                level.category = cat
                level.save()
                self.stdout.write(self.style.SUCCESS(f'Updated level: {name} ({category_code})'))
            elif created:
                self.stdout.write(self.style.SUCCESS(f'Created level: {name} ({category_code})'))
            else:
                self.stdout.write(f'Level already exists: {name} ({category_code})')
        self.stdout.write(self.style.SUCCESS('Default levels set up successfully!'))

