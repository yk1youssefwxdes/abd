"""
WSGI config for school_erp project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os
from core.license import validate_or_exit

from django.core.wsgi import get_wsgi_application

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'school_erp.settings')

# Validate early in WSGI initialization
validate_or_exit()

application = get_wsgi_application()
