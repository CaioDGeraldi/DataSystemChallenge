from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.usuarios.validators import normalizar_cpf, validar_cpf

from .models import Cliente


def cadastrar_cliente(*, empresa, cpf, senha, confirmacao, first_name="", last_name="", request=None):
    cpf = normalizar_cpf(cpf)
    validar_cpf(cpf)
    if not senha or senha != confirmacao:
        raise ValidationError("A senha e a confirmação devem coincidir e não podem estar vazias.")
    Usuario = get_user_model()
    with transaction.atomic():
        usuario = Usuario.objects.select_for_update().filter(cpf=cpf).first()
        novo = False
        if usuario is None:
            first_name, last_name = first_name.strip(), last_name.strip()
            if not first_name or not last_name:
                raise ValidationError("Nome e sobrenome são obrigatórios para uma nova identidade.")
            candidato = Usuario(cpf=cpf, first_name=first_name, last_name=last_name)
            validate_password(senha, candidato)
            try:
                # Savepoint: uma disputa pelo CPF não invalida a transação externa.
                with transaction.atomic():
                    usuario = Usuario.objects.create_user(
                        cpf, senha, first_name=first_name, last_name=last_name
                    )
                novo = True
            except (IntegrityError, ValidationError):
                usuario = Usuario.objects.select_for_update().filter(cpf=cpf).first()
                if usuario is None:
                    raise
        if not novo:
            autenticado = authenticate(request, cpf=cpf, password=senha)
            if autenticado is None or autenticado.pk != usuario.pk:
                raise ValidationError("Não foi possível autenticar com o CPF e a senha informados.")
        cliente, _ = Cliente.objects.get_or_create(usuario=usuario, empresa=empresa)
        return cliente
