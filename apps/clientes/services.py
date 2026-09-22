from django.db import transaction

from apps.usuarios.services import resolver_identidade

from .models import Cliente


def cadastrar_cliente(*, empresa, cpf, senha, confirmacao, first_name="", last_name="", request=None):
    with transaction.atomic():
        usuario = resolver_identidade(
            cpf=cpf, senha=senha, confirmacao=confirmacao,
            first_name=first_name, last_name=last_name, request=request,
        )
        cliente, _ = Cliente.objects.get_or_create(usuario=usuario, empresa=empresa)
        return cliente
