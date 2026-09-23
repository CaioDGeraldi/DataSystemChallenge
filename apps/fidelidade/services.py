from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction

from apps.clientes.models import Cliente
from apps.empresas.models import Loja
from apps.empresas.services import exigir_loja_autorizada, resolver_configuracao
from apps.usuarios.validators import normalizar_cpf, validar_cpf

from .exceptions import ClienteNaoEncontrado, IdempotenciaConflitante, LojaForaDoEscopo
from .calculos import calcular_expiracao, calcular_pontos
from .models import Compra, LotePontos
from .eventos import resolver_efeito_evento, registrar_aplicacao_evento
from .escrita_eventos import _permitir_escrita_eventos


def _criar_lote_da_nova_compra(compra):
    """Somente após vencer o INSERT, dentro da transação de registrar_compra."""
    politica = resolver_configuracao(compra.loja.empresa, compra.loja)
    efeito = resolver_efeito_evento(compra.loja, compra.ocorrida_em)
    multiplicador = efeito.valor if efeito is not None else Decimal("1.0000")
    base, concedidos = calcular_pontos(
        compra.valor, politica.pontos_por_real, politica.precisao_pontos,
        politica.modo_arredondamento_pontos, multiplicador,
    )
    lote = LotePontos.objects.create(
        compra=compra, cliente_id=compra.cliente_id,
        pontos_base=base, pontos_concedidos=concedidos,
        multiplicador_pontos_aplicado=multiplicador,
        pontos_por_real_aplicado=politica.pontos_por_real,
        precisao_pontos_aplicada=politica.precisao_pontos,
        modo_arredondamento_aplicado=politica.modo_arredondamento_pontos,
        validade_pontos_meses_aplicada=politica.validade_pontos_meses,
        adquiridos_em=compra.ocorrida_em,
        expira_em=calcular_expiracao(compra.ocorrida_em, politica.validade_pontos_meses),
    )
    if efeito is not None:
        with _permitir_escrita_eventos(lote):
            registrar_aplicacao_evento(lote, efeito)
    return lote


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
        _criar_lote_da_nova_compra(candidata)
        return candidata, True
