from django.views.decorators.debug import sensitive_variables
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from apps.empresas.services import autenticar_credencial


class IntegracaoAuthentication(BaseAuthentication):
    @sensitive_variables()
    def authenticate(self, request):
        credencial = autenticar_credencial(request.headers.get("X-API-Key"))
        if credencial is None:
            raise AuthenticationFailed(
                "Credencial de integração inválida.", code="credencial_invalida",
            )
        # A integração reside em request.auth; não representa um Usuario humano.
        return None, credencial

    def authenticate_header(self, request):
        return "X-API-Key"
