"""Resgate atômico com locks FEFO e simulação somente leitura das mesmas regras."""
from decimal import Context, Decimal, localcontext
from hashlib import sha256

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.empresas.models import Loja
from apps.empresas.services import exigir_loja_autorizada, resolver_configuracao
from apps.usuarios.validators import normalizar_cpf, validar_cpf

from .calculos_resgate import calcular_desconto, normalizar_identificador_resgate, validar_pontos_solicitados
from .escrita_resgates import _exigir_escrita_resgates, _permitir_escrita_resgates
from .exceptions import (
    ClienteNaoEncontrado, IdempotenciaConflitante, IncrementoResgateInvalido,
    LojaForaDoEscopo, PontosAbaixoDoMinimo, SaldoInsuficiente,
)
from .models import AlocacaoResgate, LotePontos, Resgate


def _chave_lock_resgate(loja_id, identificador):
    digest = sha256(f'resgate:{loja_id}:{identificador}'.encode('utf-8')).digest()
    return int.from_bytes(digest[:8], byteorder='big', signed=True)


def _travar_chave_resgate(loja_id, identificador):
    if not connection.in_atomic_block:
        raise RuntimeError('O advisory lock de Resgate exige transação.')
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(%s)', [_chave_lock_resgate(loja_id, identificador)])


def _comparar_retry(existente, *, loja_id, cliente_id, identificador, pontos):
    if (existente.loja_id, existente.cliente_id, existente.identificador_externo, existente.pontos_resgatados) != (
        loja_id, cliente_id, identificador, pontos,
    ):
        raise IdempotenciaConflitante
    return existente, False


def _selecionar_lotes_fefo(cliente, instante, *, travar=True):
    # Sem joins no lock: somente os Lotes são travados, na ordem de consumo.
    lotes = LotePontos.objects.filter(
        cliente_id=cliente.pk, expira_em__gt=instante,
    ).order_by('expira_em', 'adquiridos_em', 'pk')
    if travar:
        lotes = lotes.select_for_update()
    return list(lotes)


def _calcular_saldo(lotes):
    """Deriva saldo e restantes; o chamador define a garantia de concorrência."""
    consumos = dict(AlocacaoResgate.objects.filter(lote_id__in=[lote.pk for lote in lotes])
                    .values('lote_id').annotate(total=Sum('pontos_consumidos')).values_list('lote_id', 'total'))
    restantes = []
    # Cada Lote tem até 24 dígitos. A soma cresce com o número de Lotes.
    with localcontext(Context(prec=40 + len(str(len(lotes))))):
        saldo = Decimal('0.0000')
        for lote in lotes:
            restante = lote.pontos_concedidos - consumos.get(lote.pk, Decimal('0.0000'))
            if restante < 0:
                raise ValidationError('O histórico de consumo do Lote excede sua concessão.')
            if restante:
                restantes.append((lote, restante))
                saldo += restante
        return saldo, restantes


def _criar_alocacoes(resgate, restantes):
    _exigir_escrita_resgates(resgate)
    with localcontext(Context(prec=40)):
        faltam = resgate.pontos_resgatados
        for lote, restante in restantes:
            if not faltam:
                break
            consumo = min(faltam, restante)
            alocacao = AlocacaoResgate(resgate=resgate, lote=lote, pontos_consumidos=consumo)
            with _permitir_escrita_resgates(alocacao):
                alocacao.save(force_insert=True)
            faltam -= consumo
        if faltam:
            raise ValidationError('As alocações não completam os pontos do Resgate.')


def _avaliar_resgate(lotes, politica, pontos, quantidade):
    # O request já foi validado como int; módulo inteiro não depende do
    # contexto Decimal do chamador. Quantidade Decimal é usada na persistência.
    if pontos < politica.resgate_minimo_pontos:
        raise PontosAbaixoDoMinimo
    if (pontos - politica.resgate_minimo_pontos) % politica.incremento_resgate_pontos:
        raise IncrementoResgateInvalido
    saldo, restantes = _calcular_saldo(lotes)
    if saldo < quantidade:
        raise SaldoInsuficiente
    desconto = calcular_desconto(quantidade, politica.valor_monetario_por_ponto)
    return saldo, restantes, desconto


def _autorizar_loja(credencial, loja_id):
    loja = Loja.objects.select_related("empresa").filter(pk=loja_id).first()
    if loja is None:
        raise LojaForaDoEscopo
    try:
        loja = exigir_loja_autorizada(credencial, loja)
    except PermissionDenied:
        raise LojaForaDoEscopo from None
    return loja


def registrar_resgate(*, credencial, loja_id, cliente_cpf, identificador_externo, pontos):
    with transaction.atomic():
        loja = _autorizar_loja(credencial, loja_id)
        identificador = normalizar_identificador_resgate(identificador_externo)
        quantidade = validar_pontos_solicitados(pontos)
        cpf = normalizar_cpf(cliente_cpf)
        validar_cpf(cpf)
        _travar_chave_resgate(loja.pk, identificador)
        chave = {'loja_id': loja.pk, 'identificador_externo': identificador}
        existente = Resgate.objects.filter(**chave).first()
        cliente = Cliente.objects.select_related('usuario').filter(empresa_id=loja.empresa_id, usuario__cpf=cpf).first()
        if cliente is None:
            raise ClienteNaoEncontrado
        fatos = dict(loja_id=loja.pk, cliente_id=cliente.pk, identificador=identificador, pontos=quantidade)
        if existente is not None:
            return _comparar_retry(existente, **fatos)

        # NO KEY UPDATE serializa resgates sem bloquear FK de novas Compras/Lotes.
        # Compra toma lock da Empresa para campanhas; Resgate não toma esse lock.
        Cliente.objects.select_for_update(no_key=True).get(pk=cliente.pk)
        instante = timezone.now()  # Único instante da operação nova, após espera pelo Cliente.
        lotes = _selecionar_lotes_fefo(cliente, instante)
        politica = resolver_configuracao(loja.empresa, loja)
        saldo, restantes, desconto = _avaliar_resgate(lotes, politica, pontos, quantidade)
        resgate = Resgate(
            loja=loja, cliente=cliente, credencial_origem_id=credencial.pk,
            identificador_externo=identificador, pontos_resgatados=quantidade,
            resgate_minimo_pontos_aplicado=politica.resgate_minimo_pontos,
            incremento_resgate_pontos_aplicado=politica.incremento_resgate_pontos,
            valor_monetario_por_ponto_aplicado=politica.valor_monetario_por_ponto,
            valor_desconto=desconto, resgatado_em=instante,
        )
        try:
            with transaction.atomic(), _permitir_escrita_resgates(resgate):
                resgate.save(force_insert=True)
        except IntegrityError as exc:
            diagnostico = getattr(exc.__cause__, 'diag', None)
            if getattr(diagnostico, 'constraint_name', None) != 'resgate_loja_identificador_unico':
                raise
            return _comparar_retry(Resgate.objects.get(**chave), **fatos)
        with _permitir_escrita_resgates(resgate):
            _criar_alocacoes(resgate, restantes)
        # Verificação persistida antes do commit: nem falha parcial nem implementação
        # alternativa do helper pode deixar Resgate com conjunto incompleto.
        total = resgate.alocacoes.aggregate(total=Sum('pontos_consumidos'))['total']
        if total != quantidade:
            raise ValidationError('A soma das alocações deve corresponder aos pontos do Resgate.')
        return resgate, True

def simular_resgate(*, credencial, loja_id, cliente_cpf, pontos):
    """Leitura momentânea, sem locks, persistência, idempotência ou reserva."""
    instante = timezone.now()
    loja = _autorizar_loja(credencial, loja_id)
    quantidade = validar_pontos_solicitados(pontos)
    cpf = normalizar_cpf(cliente_cpf)
    validar_cpf(cpf)
    cliente = Cliente.objects.select_related('usuario').filter(
        empresa_id=loja.empresa_id, usuario__cpf=cpf,
    ).first()
    if cliente is None:
        raise ClienteNaoEncontrado
    lotes = _selecionar_lotes_fefo(cliente, instante, travar=False)
    politica = resolver_configuracao(loja.empresa, loja)
    saldo, _, desconto = _avaliar_resgate(lotes, politica, pontos, quantidade)
    with localcontext(Context(prec=40 + len(str(len(lotes))))):
        projetado = saldo - quantidade
    return {
        'cliente': {'cpf': cliente.usuario.cpf, 'nome': cliente.usuario.get_full_name().strip()},
        'simulada_em': instante,
        'pontos_resgatados': pontos,
        'valor_desconto': desconto,
        'saldo': {'atual': format(saldo, '.4f'), 'projetado': format(projetado, '.4f')},
    }
