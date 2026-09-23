from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction

from apps.clientes.models import Cliente
from apps.empresas.models import Loja
from apps.empresas.services import exigir_loja_autorizada
from apps.usuarios.validators import normalizar_cpf, validar_cpf

from .exceptions import ClienteNaoEncontrado, IdempotenciaConflitante, LojaForaDoEscopo
from .models import Compra


def _comparar_fatos(existente, candidata):
    campos = ("loja_id", "cliente_id", "valor", "ocorrida_em")
    if any(getattr(existente, campo) != getattr(candidata, campo) for campo in campos):
        raise IdempotenciaConflitante
    return existente, False


def registrar_compra(*, credencial, loja_id, cliente_cpf, identificador_externo, valor, ocorrida_em):
    with transaction.atomic():
        loja = Loja.objects.filter(pk=loja_id).first()
        if loja is None:
            raise LojaForaDoEscopo
        try:
            loja = exigir_loja_autorizada(credencial, loja)
        except PermissionDenied:
            raise LojaForaDoEscopo from None
        cpf = normalizar_cpf(cliente_cpf)
        validar_cpf(cpf)
        cliente = Cliente.objects.select_related("usuario").filter(
            empresa_id=loja.empresa_id, usuario__cpf=cpf,
        ).first()
        if cliente is None:
            raise ClienteNaoEncontrado
        candidata = Compra(
            loja=loja, cliente=cliente, credencial_origem_id=credencial.pk,
            identificador_externo=identificador_externo, valor=valor, ocorrida_em=ocorrida_em,
        )
        candidata.full_clean(validate_constraints=False)
        chave = {"loja_id": loja.pk, "identificador_externo": candidata.identificador_externo}
        existente = Compra.objects.filter(**chave).first()
        if existente is not None:
            return _comparar_fatos(existente, candidata)
        try:
            # Savepoint: após a disputa de unicidade, a transação externa segue utilizável.
            with transaction.atomic():
                candidata.save(force_insert=True)
        except IntegrityError as exc:
            # Não disfarçar outras falhas de integridade como retry/conflito.
            diagnostico = getattr(exc.__cause__, "diag", None)
            if getattr(diagnostico, "constraint_name", None) != "compra_loja_identificador_unico":
                raise
            existente = Compra.objects.get(**chave)
            return _comparar_fatos(existente, candidata)
        return candidata, True
