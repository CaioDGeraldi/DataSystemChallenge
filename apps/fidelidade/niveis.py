"""Nível usa concessões históricas; saldo e atividade são dimensões separadas."""
from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum

from apps.clientes.models import Cliente
from apps.empresas.models import Empresa
from apps.empresas.services import _administrador_bloqueado, exigir_administrador

from .escrita_niveis import _permitir_escrita_nivel
from .models import LotePontos, NivelFidelidade


@dataclass(frozen=True)
class ClassificacaoNivel:
    nivel: NivelFidelidade | None
    pontos_para_nivel: Decimal


def classificar_cliente(cliente: Cliente) -> ClassificacaoNivel:
    if not isinstance(cliente, Cliente) or cliente.pk is None:
        raise ValidationError('Informe um Cliente persistido.')
    persistido = Cliente.objects.filter(pk=cliente.pk).only('empresa_id', 'usuario_id').first()
    if persistido is None or (
        cliente.empresa_id, cliente.usuario_id
    ) != (persistido.empresa_id, persistido.usuario_id):
        raise ValidationError('Cliente divergente do vínculo persistido.')
    # SUM(numeric) no PostgreSQL não limita o total à capacidade de um único Lote.
    # Nenhuma soma Python dependente da precisão Decimal global, nem quantização.
    pontos = LotePontos.objects.filter(cliente_id=persistido.pk).aggregate(
        total=Sum('pontos_concedidos'),
    )['total']
    if pontos is None:
        pontos = Decimal('0.0000')
    nivel = NivelFidelidade.objects.filter(empresa_id=persistido.empresa_id,
                                         pontos_minimos__lte=pontos).order_by(
        '-pontos_minimos',
    ).first()
    return ClassificacaoNivel(nivel=nivel, pontos_para_nivel=pontos)


def listar_niveis(request):
    membro = exigir_administrador(request)
    return NivelFidelidade.objects.filter(empresa_id=membro.empresa_id).order_by(
        'pontos_minimos',
    )


def nivel_para_gestao(request, nivel_id):
    nivel = listar_niveis(request).filter(pk=nivel_id).first()
    if nivel is None:
        raise PermissionDenied('Nível não autorizado neste contexto.')
    return nivel


def _travar_configuracao(request):
    contexto = exigir_administrador(request)
    # Mesma ordem de Eventos e parâmetros: Empresa → MembroAdministrador.
    empresa = Empresa.objects.select_for_update(no_key=True).get(pk=contexto.empresa_id)
    _administrador_bloqueado(request)
    return empresa


def _validar_configuracao(empresa):
    menor = NivelFidelidade.objects.filter(empresa=empresa).order_by('pontos_minimos').values_list(
        'pontos_minimos',
        flat=True,
    ).first()
    if menor is not None and menor != 0:
        raise ValidationError(
            'Mantenha um nível em zero enquanto houver níveis configurados.',
        )


@transaction.atomic
def criar_nivel(
    request,
    *,
    nome,
    pontos_minimos,
    bonus_pontos_percentual=Decimal("0"),
    desconto_percentual=Decimal("0"),
):
    empresa = _travar_configuracao(request)
    nivel = NivelFidelidade(
        empresa=empresa,
        nome=nome,
        pontos_minimos=pontos_minimos,
        bonus_pontos_percentual=bonus_pontos_percentual,
        desconto_percentual=desconto_percentual,
    )
    with _permitir_escrita_nivel(nivel):
        nivel.save(force_insert=True)
    _validar_configuracao(empresa)
    return nivel


@transaction.atomic
def editar_nivel(
    request,
    nivel_id,
    *,
    nome,
    pontos_minimos,
    bonus_pontos_percentual=None,
    desconto_percentual=None,
):
    empresa = _travar_configuracao(request)
    nivel = nivel_para_gestao(request, nivel_id)  # Reconsulta sob o lock; não salva instância antiga.
    nivel.nome, nivel.pontos_minimos = nome, pontos_minimos
    if bonus_pontos_percentual is not None:
        nivel.bonus_pontos_percentual = bonus_pontos_percentual
    if desconto_percentual is not None:
        nivel.desconto_percentual = desconto_percentual
    with _permitir_escrita_nivel(nivel):
        nivel.save()
    _validar_configuracao(empresa)
    return nivel


@transaction.atomic
def excluir_nivel(request, nivel_id):
    empresa = _travar_configuracao(request)
    nivel = nivel_para_gestao(request, nivel_id)
    with _permitir_escrita_nivel(nivel):
        nivel.delete()
    # A transação desfaz o DELETE se restarem níveis sem início em zero.
    # Excluir o último nível é válido: Empresa sem configuração retorna None.
    _validar_configuracao(empresa)
