"""
Django management command to generate and load comprehensive demo data.
Usage:
    python manage.py load_demo_data
    python manage.py load_demo_data --force
    python manage.py load_demo_data --students 50 --teachers 10
"""
import os
from django.core.management.base import BaseCommand
from django.core.management import call_command
from core.models import Student
from core.fixtures import generate_fixtures


class Command(BaseCommand):
    help = "Generates and loads production-quality demo/seed data for School ERP"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force reload demo data even if database already contains students",
        )
        parser.add_argument(
            "--students",
            type=int,
            default=int(os.environ.get("DEMO_NUM_STUDENTS", 60)),
            help="Number of students to generate (default: 60)",
        )
        parser.add_argument(
            "--teachers",
            type=int,
            default=int(os.environ.get("DEMO_NUM_TEACHERS", 10)),
            help="Number of teachers to generate (default: 10)",
        )
        parser.add_argument(
            "--rooms",
            type=int,
            default=int(os.environ.get("DEMO_NUM_ROOMS", 6)),
            help="Number of rooms to generate (default: 6)",
        )
        parser.add_argument(
            "--courses",
            type=int,
            default=int(os.environ.get("DEMO_NUM_COURSES", 16)),
            help="Number of course groups to generate (default: 16)",
        )
        parser.add_argument(
            "--upgrade-academic",
            action="store_true",
            help="Fait progresser automatiquement les élèves académiques d'une année après génération",
        )

    def handle(self, *args, **options):
        force = options["force"] or os.environ.get("FORCE_DEMO_DATA", "").lower() in ("true", "1", "yes")
        has_students = Student.objects.exists()

        if has_students and not force:
            self.stdout.write(
                self.style.WARNING(
                    "Database already contains student records. Skipping demo data generation. "
                    "(Use --force or FORCE_DEMO_DATA=true to overwrite)"
                )
            )
            return

        self.stdout.write(self.style.NOTICE("[*] Generating demo dataset for School ERP..."))
        generate_fixtures(
            num_rooms=options["rooms"],
            num_teachers=options["teachers"],
            num_courses=options["courses"],
            num_students=options["students"],
        )

        # Ensure default superuser admin/1234 exists
        try:
            call_command("initadmin")
        except Exception:
            pass

        if options.get("upgrade_academic"):
            self.stdout.write(self.style.NOTICE("[*] Simulation du passage annuel des niveaux académiques..."))
            try:
                call_command("upgrade_academic_levels")
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Erreur lors du passage des niveaux: {e}"))

        self.stdout.write(self.style.SUCCESS("[✔] Demo data loaded successfully!"))
