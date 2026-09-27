from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Sum

from apps.clientes.models import Cliente
from apps.empresas.models import Loja, Empresa
from apps.empresas.services import exigir_loja_autorizada, resolver_configuracao
from apps.usuarios.validators import normalizar_cpf, validar_cpf

from .exceptions import ClienteNaoEncontrado, IdempotenciaConflitante, LojaForaDoEscopo
from .calculos import calcular_expiracao
from .models import Compra, LotePontos, NivelFidelidade, Resgate, EstornoResgate
from .calculos_resgate import normalizar_identificador_resgate, maximo_desconto_compra
from .exceptions import ResgateNaoEncontrado, ResgateJaEstornado, ResgateVinculadoCompra, LimiteResgateExcedido
from .beneficios import NivelBeneficios, avaliar_fidelidade_compra, snapshot_beneficios
from .eventos import resolver_efeito_evento, registrar_aplicacao_evento
from .escrita_eventos import _permitir_escrita_eventos


def _criar_lote_da_nova_compra(compra):
    """Somente após vencer o INSERT, dentro da transação de registrar_compra."""
    politica = resolver_configuracao(compra.loja.empresa, compra.loja)
    efeito = resolver_efeito_evento(compra.loja, compra.ocorrida_em)
    multiplicador = efeito.valor if efeito is not None else Decimal("1.0000")
    anteriores = Compra.objects.filter(
        cliente_id=compra.cliente_id,
    ).exclude(pk=compra.pk)
    ultima = (
        anteriores.filter(ocorrida_em__lte=compra.ocorrida_em)
        .order_by('-ocorrida_em', '-pk')
        .values_list('ocorrida_em', flat=True)
        .first()
    )
    progresso = LotePontos.objects.filter(cliente_id=compra.cliente_id).aggregate(
        total=Sum('pontos_concedidos'),
    )['total'] or Decimal('0.0000')
    niveis = [
        NivelBeneficios(
            n.pk,
            n.nome,
            n.pontos_minimos,
            n.bonus_pontos_percentual,
            n.desconto_percentual,
        )
        for n in NivelFidelidade.objects.filter(
            empresa_id=compra.loja.empresa_id,
        )
    ]
    avaliacao = avaliar_fidelidade_compra(
        valor=compra.valor,
        politica=politica,
        instante=compra.ocorrida_em,
        ultima_compra=ultima,
        progresso=progresso,
        niveis=niveis,
        multiplicador=multiplicador,
        desconto_resgate=compra.resgate.valor_desconto if compra.resgate_id else Decimal('0.00'),
    )
    if compra.resgate_id and compra.resgate.valor_desconto > maximo_desconto_compra(
        compra.valor, politica, avaliacao.desconto_nivel, avaliacao.desconto_retorno,
    ):
        raise LimiteResgateExcedido
    lote = LotePontos.objects.create(
        compra=compra,
        cliente_id=compra.cliente_id,
        pontos_base=avaliacao.pontos_base,
        pontos_concedidos=avaliacao.pontos_concedidos,
        beneficios_aplicados=snapshot_beneficios(
            avaliacao, politica, progresso, ultima,
            desconto_resgate=compra.resgate.valor_desconto if compra.resgate_id else Decimal("0.00"),
        ),
        multiplicador_pontos_aplicado=multiplicador,
        pontos_por_real_aplicado=politica.pontos_por_real,
        precisao_pontos_aplicada=politica.precisao_pontos,
        modo_arredondamento_aplicado=politica.modo_arredondamento_pontos,
        validade_pontos_meses_aplicada=politica.validade_pontos_meses,
        adquiridos_em=compra.ocorrida_em,
        expira_em=calcular_expiracao(
            compra.ocorrida_em, politica.validade_pontos_meses,
        ),
    )
    if efeito is not None:
        with _permitir_escrita_eventos(lote):
            registrar_aplicacao_evento(lote, efeito)
    return lote


def _comparar_fatos(existente, candidata, identificador_resgate):
    historico = existente.resgate.identificador_externo if existente.resgate_id else None
    if historico != identificador_resgate:
        raise IdempotenciaConflitante
    campos = ("loja_id", "cliente_id", "valor", "ocorrida_em")
    if any(getattr(existente, campo) != getattr(candidata, campo) for campo in campos):
        raise IdempotenciaConflitante
    return existente, False


def registrar_compra(
    *,
    credencial,
    loja_id,
    cliente_cpf,
    identificador_externo,
    valor,
    ocorrida_em,
    resgate_identificador_externo=None,
):
    if resgate_identificador_externo is not None:
        resgate_identificador_externo = normalizar_identificador_resgate(resgate_identificador_externo)
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
            empresa_id=loja.empresa_id,
            usuario__cpf=cpf,
        ).first()
        if cliente is None:
            raise ClienteNaoEncontrado
        candidata = Compra(
            loja=loja,
            cliente=cliente,
            credencial_origem_id=credencial.pk,
            identificador_externo=identificador_externo,
            valor=valor,
            ocorrida_em=ocorrida_em,
        )
        candidata.full_clean(validate_constraints=False)
        chave = {
            "loja_id": loja.pk,
            "identificador_externo": candidata.identificador_externo,
        }
        existente = Compra.objects.filter(**chave).first()
        if existente is not None:
            return _comparar_fatos(existente, candidata, resgate_identificador_externo)
        # Empresa → Cliente: configuração/níveis/eventos não mudam durante a avaliação.
        # O Cliente serializa também com Resgate, sem inverter sua ordem de locks.
        Empresa.objects.select_for_update(no_key=True).get(pk=loja.empresa_id)
        Cliente.objects.select_for_update().get(pk=cliente.pk)
        existente = Compra.objects.filter(**chave).first()
        if existente is not None:
            return _comparar_fatos(existente, candidata, resgate_identificador_externo)
        if resgate_identificador_externo is not None:
            # Cliente já travado: serializa vínculo, consumo e estorno sem inverter locks.
            resgate = Resgate.objects.filter(
                loja_id=loja.pk, cliente_id=cliente.pk,
                identificador_externo=resgate_identificador_externo,
            ).first()
            if resgate is None:
                raise ResgateNaoEncontrado
            if EstornoResgate.objects.filter(resgate=resgate).exists():
                raise ResgateJaEstornado
            if Compra.objects.filter(resgate=resgate).exists():
                raise ResgateVinculadoCompra
            candidata.resgate = resgate
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
            return _comparar_fatos(existente, candidata, resgate_identificador_externo)
        _criar_lote_da_nova_compra(candidata)
        return candidata, True
