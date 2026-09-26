"""Casos de uso de campanha. O lock da Empresa serializa definição e concessão."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.empresas.models import Empresa, Loja
from apps.empresas.services import exigir_administrador, _administrador_bloqueado

from .escrita_eventos import _exigir_escrita_eventos, _permitir_escrita_eventos
from .models import AplicacaoEfeitoEventoLote, EfeitoEvento, EventoFidelidade, EventoLoja


def validar_escopo_evento(empresa, escopo, lojas):
    lojas = list(lojas)
    ids = {loja.pk for loja in lojas}
    if escopo not in EventoFidelidade.Escopo.values:
        raise ValidationError({'escopo': 'Escopo inválido.'})
    if escopo == 'EMPRESA' and lojas:
        raise ValidationError({'lojas': 'Evento EMPRESA não recebe seleção de Lojas.'})
    if escopo == 'LOJAS' and not lojas:
        raise ValidationError({'lojas': 'Selecione ao menos uma Loja.'})
    selecionadas = list(Loja.objects.filter(empresa_id=empresa.pk, pk__in=ids).order_by('pk'))
    if None in ids or len(selecionadas) != len(ids):
        raise ValidationError({'lojas': 'Todas as Lojas devem pertencer à Empresa ativa.'})
    return selecionadas


def exigir_ausencia_conflito(evento, lojas, tipos):
    """Executada sob o lock da Empresa no service de criação."""
    candidatos = EventoFidelidade.objects.filter(
        empresa_id=evento.empresa_id, cancelado_em__isnull=True,
        inicio_em__lte=evento.fim_em, fim_em__gte=evento.inicio_em,
        efeitos__tipo__in=tipos,
    )
    if evento.escopo == 'LOJAS':
        candidatos = candidatos.filter(Q(escopo='EMPRESA') | Q(lojas_selecionadas__loja__in=lojas))
    if candidatos.exists():
        raise ValidationError('Existe campanha do mesmo tipo com período e escopo sobrepostos.')


@transaction.atomic
def criar_evento(request, *, nome, descricao='', inicio_em, fim_em, escopo, efeitos, lojas=()):
    contexto = exigir_administrador(request)
    empresa = Empresa.objects.select_for_update(no_key=True).get(pk=contexto.empresa_id)
    criador = _administrador_bloqueado(request)
    selecionadas = validar_escopo_evento(empresa, escopo, lojas)
    evento = EventoFidelidade(empresa=empresa, nome=nome, descricao=descricao, inicio_em=inicio_em,
                             fim_em=fim_em, escopo=escopo, criado_por=criador)
    evento.full_clean()
    efeitos = list(efeitos)
    if not efeitos:
        raise ValidationError('Informe ao menos um efeito.')
    tipos = [efeito['tipo'] for efeito in efeitos]
    if len(set(tipos)) != len(tipos):
        raise ValidationError('Um Evento não pode repetir o mesmo tipo de efeito.')
    exigir_ausencia_conflito(evento, selecionadas, tipos)
    with _permitir_escrita_eventos(evento):
        evento.save()
    for dados in efeitos:
        efeito = EfeitoEvento(evento=evento, tipo=dados['tipo'], valor=dados['valor'])
        with _permitir_escrita_eventos(efeito):
            efeito.save()
    for loja in selecionadas:
        relacao = EventoLoja(evento=evento, loja=loja)
        with _permitir_escrita_eventos(relacao):
            relacao.save()
    return evento


@transaction.atomic
def cancelar_evento(request, evento_id):
    contexto = exigir_administrador(request)
    Empresa.objects.select_for_update(no_key=True).get(pk=contexto.empresa_id)
    _administrador_bloqueado(request)
    evento = EventoFidelidade.objects.select_for_update().filter(pk=evento_id, empresa_id=contexto.empresa_id).first()
    if evento is None:
        raise PermissionDenied('Evento não autorizado neste contexto.')
    if evento.cancelado_em is None:
        evento.cancelado_em = timezone.now()
        with _permitir_escrita_eventos(evento):
            evento.save(update_fields=['cancelado_em'])
    return evento


def _loja_persistida_para_evento(loja):
    persistida = Loja.objects.get(pk=loja.pk)
    if persistida.empresa_id != loja.empresa_id:
        raise ValidationError("Loja divergente do tenant persistido.")
    return persistida


def _buscar_efeito_evento(persistida, ocorrida_em):
    efeitos = list(
        EfeitoEvento.objects.select_related("evento")
        .filter(
            tipo=EfeitoEvento.Tipo.MULTIPLICADOR_PONTOS,
            evento__empresa_id=persistida.empresa_id,
            evento__cancelado_em__isnull=True,
            evento__inicio_em__lte=ocorrida_em,
            evento__fim_em__gte=ocorrida_em,
        )
        .filter(
            Q(evento__escopo="EMPRESA")
            | Q(
                evento__escopo="LOJAS",
                evento__lojas_selecionadas__loja_id=persistida.pk,
            )
        )
        .distinct()
    )
    if len(efeitos) > 1:
        raise ValidationError(
            "Há campanhas conflitantes para esta operação.",
        )
    return efeitos[0] if efeitos else None


def consultar_efeito_evento(loja, ocorrida_em):
    """Consulta corrente sem lock para operações não persistentes."""
    persistida = _loja_persistida_para_evento(loja)
    return _buscar_efeito_evento(persistida, ocorrida_em)


@transaction.atomic
def resolver_efeito_evento(loja, ocorrida_em):
    """Resolve e trava a configuração para a Compra que será persistida."""
    persistida = _loja_persistida_para_evento(loja)
    Empresa.objects.select_for_update(no_key=True).get(
        pk=persistida.empresa_id,
    )
    return _buscar_efeito_evento(persistida, ocorrida_em)


def registrar_aplicacao_evento(lote, efeito):
    _exigir_escrita_eventos(lote)  # Apenas o Lote emitido nesta operação, nunca backfill.
    aplicacao = AplicacaoEfeitoEventoLote(
        lote=lote, evento_id=efeito.evento_id, efeito=efeito,
        tipo_aplicado=efeito.tipo, valor_aplicado=efeito.valor,
    )
    with _permitir_escrita_eventos(aplicacao):
        aplicacao.save()
    return aplicacao
