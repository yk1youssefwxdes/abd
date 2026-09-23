"""
Django management command to auto-upgrade all academic students to their next level.
Usage:
    python manage.py upgrade_academic_levels
    python manage.py upgrade_academic_levels --dry-run
    python manage.py upgrade_academic_levels --reason "Rentrée Scolaire 2026-2027"
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import Student, Level, LevelType, StudentLevelHistory
from core.utils import promote_student_level


class Command(BaseCommand):
    help = "Fait progresser automatiquement tous les élèves inscrits dans un niveau académique vers leur niveau suivant."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simuler le passage de niveau sans écrire en base de données",
        )
        parser.add_argument(
            "--reason",
            type=str,
            default="Passage de niveau académique annuel automatique (CLI)",
            help="Motif consigné dans l'historique",
        )
        parser.add_argument(
            "--notes",
            type=str,
            default="",
            help="Notes optionnelles pour l'historique",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        reason = options["reason"]
        notes = options["notes"]

        if dry_run:
            self.stdout.write(self.style.WARNING("=== MODE SIMULATION (DRY-RUN) - Aucune modification ne sera enregistrée ==="))

        academic_students = Student.objects.filter(
            is_active=True,
            level__isnull=False,
            level__level_type=LevelType.ACADEMIC
        ).select_related('level', 'level__next_level', 'level__category').order_by('level__order', 'name')

        total = academic_students.count()
        self.stdout.write(self.style.NOTICE(f"[*] {total} élève(s) avec niveau académique détecté(s)..."))

        upgraded = 0
        terminal = 0
        skipped = 0

        with transaction.atomic():
            for st in academic_students:
                curr_lvl = st.level
                target_lvl = curr_lvl.next_level
                if not target_lvl:
                    target_lvl = Level.objects.filter(
                        category=curr_lvl.category,
                        order__gt=curr_lvl.order,
                        level_type=LevelType.ACADEMIC
                    ).order_by('order').first()

                if not target_lvl:
                    terminal += 1
                    self.stdout.write(f"  [-] {st.name} : {curr_lvl.name} (Niveau terminal, non modifié)")
                    continue

                if dry_run:
                    upgraded += 1
                    self.stdout.write(f"  [SIMULÉ] {st.name} : {curr_lvl.name} → {target_lvl.name}")
                else:
                    success, new_lvl, msg = promote_student_level(
                        st,
                        to_level=target_lvl,
                        reason=reason,
                        notes=notes
                    )
                    if success:
                        upgraded += 1
                        self.stdout.write(self.style.SUCCESS(f"  [✔] {st.name} : {curr_lvl.name} → {target_lvl.name}"))
                    else:
                        skipped += 1
                        self.stdout.write(self.style.ERROR(f"  [✖] {st.name} : {msg}"))

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write("\n" + "=" * 50)
        self.stdout.write(self.style.SUCCESS(
            f"RÉSUMÉ : {upgraded} élève(s) promu(s), {terminal} en classe terminale, {skipped} ignoré(s)."
        ))
        if dry_run:
            self.stdout.write(self.style.WARNING("Simulation terminée : base de données intacte."))
        self.stdout.write("=" * 50)
