from drf_spectacular.extensions import OpenApiAuthenticationExtension, OpenApiSerializerExtension


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


class RegistrarResgateSchema(OpenApiSerializerExtension):
    target_class = 'apps.api.serializers.RegistrarResgateSerializer'

    def map_serializer(self, auto_schema, direction):
        schema = auto_schema._map_serializer(self.target, direction, bypass_extensions=True)
        schema['additionalProperties'] = False
        return schema


class SimularResgateSchema(RegistrarResgateSchema):
    target_class = 'apps.api.serializers.SimularResgateSerializer'
