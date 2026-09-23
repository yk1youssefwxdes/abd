from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'core'
    
    def ready(self):
        """Validate license once at application startup, not on every request."""
        from core.license import validate_or_exit
        validate_or_exit()  # Runs only once when Django starts
        import core.signals  # Registers model signals
