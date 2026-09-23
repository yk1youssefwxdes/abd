"""
ASGI config for school_erp project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os
from core.license import validate_or_exit

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'school_erp.settings')

# Validate early in ASGI initialization
validate_or_exit()

application = get_asgi_application()
