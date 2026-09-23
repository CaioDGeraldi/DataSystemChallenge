from rest_framework.permissions import BasePermission

from apps.empresas.models import CredencialIntegracao


class IntegracaoAutenticada(BasePermission):
    def has_permission(self, request, view):
        return isinstance(request.auth, CredencialIntegracao) and request.auth.ativa
