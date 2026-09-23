from django.core.management.base import BaseCommand
from django.contrib.sites.models import Site


class Command(BaseCommand):
    help = "Create or update Django Sites"

    def handle(self, *args, **options):
        sites = [
            (1, "127.0.0.1:8000", "Site One"),
            (2, "127.0.0.2:8000", "Site Two"),
        ]

        for site_id, domain, name in sites:
            Site.objects.update_or_create(
                id=site_id,
                defaults={
                    "domain": domain,
                    "name": name,
                },
            )
            self.stdout.write(
                self.style.SUCCESS(f"✓ {name} ({domain})")
            )

        self.stdout.write(self.style.SUCCESS("Sites configured successfully."))