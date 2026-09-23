"""
Management command: abd_prof
Creates the 8 predefined teachers with their subjects and teaching levels.

Usage:
    python manage.py abd_prof
    python manage.py abd_prof --dry-run
    python manage.py abd_prof --reset   # deletes and re-creates all 8 teachers
"""
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import Teacher, CourseGroup, Level, TeacherPaymentMethod


# ---------------------------------------------------------------------------
# Data: (name, subject, [level_aliases])
# Level aliases mapping:
#   3cllg / 3college  → 3ASC
#   trc / tc          → Tronc Commun (TC)
#   1bac              → 1ère année Bac (1Bac)
#   bac / 2bac        → 2ème année Bac (2Bac)
# ---------------------------------------------------------------------------
TEACHERS_DATA = [
    ("Oubaha",              "Mathématiques",   ["3cllg", "TRC", "1BAC", "BAC"]),
    ("Najib",               "SVT",             ["BAC", "3cllg"]),
    ("Youssef",             "Physique-Chimie", ["BAC", "TRC"]),
    ("Zineb",               "Physique-Chimie", ["BAC", "1BAC"]),
    ("Kessa",               "Physique-Chimie", ["3cllg", "TRC"]),
    ("Charehddinne",        "Français",        ["1BAC"]),
    ("Mouad",               "Anglais",         ["BAC"]),
    ("Makan",          "Arabe",           ["1BAC"]),
]

# Level alias (lowercase) → Level name in DB (must match setup_levels.py exactly)
LEVEL_ALIAS_MAP = {
    "3cllg":        "3ASC",
    "3college":     "3ASC",
    "3collège":     "3ASC",
    "trc":          "Tronc Commun (TC)",
    "tc":           "Tronc Commun (TC)",
    "tronc commun": "Tronc Commun (TC)",
    "1bac":         "1ère année Bac (1Bac)",
    "bac":          "2ème année Bac (2Bac)",
    "2bac":         "2ème année Bac (2Bac)",
}


class Command(BaseCommand):
    help = (
        "Adds the 8 predefined teachers (Oubaha, Najib, Youssef, Zineb, Kessa, "
        "Charehddinne, Mouad, Makan) with their subjects and levels. "
        "Uses get_or_create — safe to run multiple times."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simulate the operation without saving anything to the database.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help=(
                "Delete and recreate the 8 predefined teachers and their course groups. "
                "WARNING: this removes all associated data for these teachers."
            ),
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        reset = options["reset"]

        if dry_run:
            self.stdout.write(self.style.WARNING(
                "\n⚠  Mode simulation (--dry-run) : aucune modification ne sera sauvegardée.\n"
            ))

        # ----------------------------------------------------------------
        # 1. Resolve levels from DB
        # ----------------------------------------------------------------
        level_cache = {}   # ALIAS_UPPER → Level object
        missing_levels = []

        all_aliases = {alias for _, _, aliases in TEACHERS_DATA for alias in aliases}

        for alias in all_aliases:
            db_name = LEVEL_ALIAS_MAP.get(alias.lower())
            if db_name is None:
                missing_levels.append(f"{alias} (alias non reconnu)")
                continue
            try:
                level_obj = Level.objects.get(name=db_name)
                level_cache[alias.upper()] = level_obj
            except Level.DoesNotExist:
                missing_levels.append(f"{alias} → '{db_name}' (non trouvé en base)")

        if missing_levels:
            self.stdout.write(self.style.WARNING(
                "\n⚠  Niveaux introuvables (ils seront ignorés) :\n"
                + "\n".join(f"   • {m}" for m in missing_levels)
                + "\n\nAstuce : lancez d'abord « python manage.py setup_levels »\n"
            ))

        # ----------------------------------------------------------------
        # 2. Optionally delete existing teachers by those names
        # ----------------------------------------------------------------
        teacher_names = [name for name, _, _ in TEACHERS_DATA]

        if reset:
            if dry_run:
                count = Teacher.objects.filter(name__in=teacher_names).count()
                self.stdout.write(self.style.WARNING(
                    f"  [simulation] Suppression de {count} professeur(s) existants.\n"
                ))
            else:
                with transaction.atomic():
                    deleted, _ = Teacher.objects.filter(name__in=teacher_names).delete()
                    self.stdout.write(self.style.WARNING(
                        f"  🗑  {deleted} entrée(s) supprimée(s) (reset).\n"
                    ))

        # ----------------------------------------------------------------
        # 3. Create teachers + course groups
        # ----------------------------------------------------------------
        stats = {
            "teachers_created": 0,
            "teachers_existing": 0,
            "groups_created": 0,
            "groups_existing": 0,
        }

        self.stdout.write(self.style.NOTICE("\n=== Création des professeurs ===\n"))

        for teacher_name, subject, level_aliases in TEACHERS_DATA:
            # Resolve Level objects for this teacher
            resolved_levels = [
                level_cache[alias.upper()]
                for alias in level_aliases
                if alias.upper() in level_cache
            ]

            # -- Teacher --
            teacher_defaults = {
                "phone":              "0000000000",
                "email":              "",
                "payment_method":     TeacherPaymentMethod.PERCENTAGE,
                "payment_percentage": Decimal("50.00"),
                "hourly_rate":        Decimal("100.00"),
                "session_rate":       Decimal("100.00"),
                "is_active":          True,
            }

            if dry_run:
                exists = Teacher.objects.filter(name=teacher_name).exists()
                action = "déjà présent" if exists else "à créer"
                self.stdout.write(f"  👤 {teacher_name}  [{action}]  —  {subject}")
                if exists:
                    stats["teachers_existing"] += 1
                else:
                    stats["teachers_created"] += 1
            else:
                with transaction.atomic():
                    teacher_obj, created = Teacher.objects.get_or_create(
                        name=teacher_name,
                        defaults=teacher_defaults,
                    )
                if created:
                    stats["teachers_created"] += 1
                    self.stdout.write(self.style.SUCCESS(
                        f"  ✅ Créé  : {teacher_name}  |  {subject}"
                    ))
                else:
                    stats["teachers_existing"] += 1
                    self.stdout.write(
                        f"  ℹ  Existant: {teacher_name}  |  {subject}"
                    )

            # -- Course Groups (one per level) --
            for level_obj in resolved_levels:
                group_name = f"{subject} – {level_obj.name}"
                group_defaults = {
                    "subject":       subject,
                    "monthly_price": Decimal("200.00"),
                    "is_active":     True,
                }

                if dry_run:
                    exists = CourseGroup.objects.filter(name=group_name).exists()
                    action = "déjà présent" if exists else "à créer"
                    self.stdout.write(f"      📚 {group_name}  [{action}]")
                    if exists:
                        stats["groups_existing"] += 1
                    else:
                        stats["groups_created"] += 1
                else:
                    with transaction.atomic():
                        group, created = CourseGroup.objects.get_or_create(
                            name=group_name,
                            teacher=teacher_obj,
                            defaults=group_defaults,
                        )
                        # Always ensure the level M2M link exists
                        group.levels.add(level_obj)

                    if created:
                        stats["groups_created"] += 1
                        self.stdout.write(self.style.SUCCESS(
                            f"      ✅ Groupe créé        : {group_name}"
                        ))
                    else:
                        stats["groups_existing"] += 1
                        self.stdout.write(
                            f"      ℹ  Groupe existant   : {group_name}"
                        )

        # ----------------------------------------------------------------
        # 4. Summary
        # ----------------------------------------------------------------
        sep = "─" * 55
        self.stdout.write(f"\n{sep}")
        if dry_run:
            self.stdout.write(self.style.WARNING("  SIMULATION terminée (rien n'a été sauvegardé)"))
        else:
            self.stdout.write(self.style.SUCCESS("  ✅  abd_prof terminé avec succès !"))

        self.stdout.write(f"  👤 Professeurs créés     : {stats['teachers_created']}")
        self.stdout.write(f"  👤 Professeurs existants : {stats['teachers_existing']}")
        self.stdout.write(f"  📚 Groupes créés         : {stats['groups_created']}")
        self.stdout.write(f"  📚 Groupes existants     : {stats['groups_existing']}")
        self.stdout.write(sep)
