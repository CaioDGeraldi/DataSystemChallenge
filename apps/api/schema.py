from drf_spectacular.extensions import OpenApiAuthenticationExtension


class IntegracaoAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "apps.api.authentication.IntegracaoAuthentication"
    name = "X-API-Key"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "Chave no formato <identificador>.<segredo>. O segredo é exibido somente na criação.",
        }
