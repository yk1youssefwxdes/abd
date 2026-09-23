#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'school_erp.settings')
    # Protect manage.py entrypoint
    try:
        from core.license import validate_or_exit
        validate_or_exit()
    except Exception:
        # If the license module is not importable for any reason,
        # fail closed to avoid accidentally allowing execution.
        raise SystemExit("This copy of the application is not licensed for this device.")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
