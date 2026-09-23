from django.core.management.base import BaseCommand
from core.models import Level, LevelCategory, LevelType


class Command(BaseCommand):
    help = 'Create default academic and non-academic levels with progression orders and links'

    # (code, name, is_academic)
    CATEGORIES = [
        # Catégories Académiques
        ('GARDERIE', 'La Garderie', True),
        ('PRIMAIRE', 'Primaire', True),
        ('COLLEGE', 'Collège', True),
        ('LYCEE', 'Lycée', True),
        # Catégories Non Académiques
        ('LANGUES', 'Langues & Communication', False),
        ('PARASCOLAIRE', 'Parascolaire & Activités', False),
        ('SOUTIEN_LIBRE', 'Formation & Soutien Libre', False),
    ]

    # (name, category_code, level_type, order)
    ACADEMIC_LEVELS = [
        # Garderie
        ('Petite Section (PS)', 'GARDERIE', LevelType.ACADEMIC, 1),
        ('Moyenne Section (MS)', 'GARDERIE', LevelType.ACADEMIC, 2),
        ('Grande Section (GS)', 'GARDERIE', LevelType.ACADEMIC, 3),
        # Primaire
        ('1AP', 'PRIMAIRE', LevelType.ACADEMIC, 4),
        ('2AP', 'PRIMAIRE', LevelType.ACADEMIC, 5),
        ('3AP', 'PRIMAIRE', LevelType.ACADEMIC, 6),
        ('4AP', 'PRIMAIRE', LevelType.ACADEMIC, 7),
        ('5AP', 'PRIMAIRE', LevelType.ACADEMIC, 8),
        ('6AP', 'PRIMAIRE', LevelType.ACADEMIC, 9),
        # Collège
        ('1ASC', 'COLLEGE', LevelType.ACADEMIC, 10),
        ('2ASC', 'COLLEGE', LevelType.ACADEMIC, 11),
        ('3ASC', 'COLLEGE', LevelType.ACADEMIC, 12),
        # Lycée
        ('Tronc Commun (TC)', 'LYCEE', LevelType.ACADEMIC, 13),
        ('1ère année Bac (1Bac)', 'LYCEE', LevelType.ACADEMIC, 14),
        ('2ème année Bac (2Bac)', 'LYCEE', LevelType.ACADEMIC, 15),
    ]

    NON_ACADEMIC_LEVELS = [
        # Langues
        ('A1 - Débutant', 'LANGUES', LevelType.NON_ACADEMIC, 1),
        ('A2 - Élémentaire', 'LANGUES', LevelType.NON_ACADEMIC, 2),
        ('B1 - Intermédiaire', 'LANGUES', LevelType.NON_ACADEMIC, 3),
        ('B2 - Avancé', 'LANGUES', LevelType.NON_ACADEMIC, 4),
        ('C1 - Expert', 'LANGUES', LevelType.NON_ACADEMIC, 5),
        ('Communication & Prise de Parole', 'LANGUES', LevelType.NON_ACADEMIC, 6),
        ('Business English', 'LANGUES', LevelType.NON_ACADEMIC, 7),
        # Parascolaire
        ('Club Robotique & IA', 'PARASCOLAIRE', LevelType.NON_ACADEMIC, 1),
        ('Club Échecs', 'PARASCOLAIRE', LevelType.NON_ACADEMIC, 2),
        ('Atelier Théâtre & Éloquence', 'PARASCOLAIRE', LevelType.NON_ACADEMIC, 3),
        ('Arts Plastiques & Dessin', 'PARASCOLAIRE', LevelType.NON_ACADEMIC, 4),
        # Soutien Libre
        ('Remise à niveau continue', 'SOUTIEN_LIBRE', LevelType.NON_ACADEMIC, 1),
        ('Préparation Concours d\'excellence', 'SOUTIEN_LIBRE', LevelType.NON_ACADEMIC, 2),
        ('Coaching & Méthodologie', 'SOUTIEN_LIBRE', LevelType.NON_ACADEMIC, 3),
    ]

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE('Configuration des niveaux académiques et non-académiques...'))

        # 1. Catégories
        category_map = {}
        for code, name, is_acad in self.CATEGORIES:
            cat, created = LevelCategory.objects.get_or_create(
                code=code,
                defaults={'name': name, 'is_academic': is_acad}
            )
            if not created:
                updated = False
                if cat.name != name:
                    cat.name = name
                    updated = True
                if cat.is_academic != is_acad:
                    cat.is_academic = is_acad
                    updated = True
                if updated:
                    cat.save()
            category_map[code] = cat

        # 2. Niveaux Académiques
        created_academic = []
        for name, category_code, lvl_type, order in self.ACADEMIC_LEVELS:
            cat = category_map[category_code]
            level, created = Level.objects.get_or_create(
                name=name,
                defaults={'category': cat, 'level_type': lvl_type, 'order': order}
            )
            level.category = cat
            level.level_type = lvl_type
            level.order = order
            level.save()
            created_academic.append(level)
            status = 'Créé' if created else 'Mis à jour'
            self.stdout.write(f'  [Académique] {status}: {name} (Ordre {order})')

        # Relier automatiquement next_level pour chaque niveau académique consécutif
        for i in range(len(created_academic) - 1):
            curr_lvl = created_academic[i]
            nxt_lvl = created_academic[i + 1]
            curr_lvl.next_level = nxt_lvl
            curr_lvl.save(update_fields=['next_level'])

        # Le dernier niveau académique (2Bac) n'a pas de next_level (classe terminale)
        if created_academic:
            created_academic[-1].next_level = None
            created_academic[-1].save(update_fields=['next_level'])

        # 3. Niveaux Non-Académiques
        for name, category_code, lvl_type, order in self.NON_ACADEMIC_LEVELS:
            cat = category_map[category_code]
            level, created = Level.objects.get_or_create(
                name=name,
                defaults={'category': cat, 'level_type': lvl_type, 'order': order}
            )
            level.category = cat
            level.level_type = lvl_type
            level.order = order
            level.next_level = None  # Non-académique n'a pas de progression annuelle automatique
            level.save()
            status = 'Créé' if created else 'Mis à jour'
            self.stdout.write(f'  [Non-Académique] {status}: {name}')

        total_acad = Level.objects.filter(level_type=LevelType.ACADEMIC).count()
        total_non_acad = Level.objects.filter(level_type=LevelType.NON_ACADEMIC).count()
        self.stdout.write(self.style.SUCCESS(
            f'Configuration terminée avec succès ! '
            f'({total_acad} niveaux académiques chaînés, {total_non_acad} niveaux non-académiques).'
        ))

