from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.api"

    def ready(self):
        # Registra a extensão de autenticação no gerador OpenAPI.
        from . import schema  # noqa: F401
