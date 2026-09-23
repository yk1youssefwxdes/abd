"""
Automatic Superuser initialization command for cloud & server deployments.
Creates or updates the default superuser (admin / 1234) automatically.
"""
import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = "Automatically creates or updates the default superuser account (admin / 1234)"

    def handle(self, *args, **options):
        User = get_user_model()
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "admin").strip()
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "1234").strip()
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "admin@school-erp.com").strip()

        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "email": email,
                "is_staff": True,
                "is_superuser": True,
            },
        )

        user.set_password(password)
        user.is_staff = True
        user.is_superuser = True
        user.save()

        if created:
            self.stdout.write(self.style.SUCCESS(f"Superuser '{username}' created successfully with password '{password}'."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Superuser '{username}' password refreshed to '{password}'."))
