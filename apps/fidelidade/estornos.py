"""Estorno integral e histórico, serializado com Resgates do mesmo Cliente."""
from hashlib import sha256

from django.db import connection, transaction
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.empresas.services import resolver_configuracao

from .calculos_resgate import normalizar_identificador_resgate
from .escrita_resgates import _permitir_escrita_resgates
from .exceptions import IdempotenciaConflitante, ResgateJaEstornado, ResgateNaoEncontrado
from .models import EstornoResgate, Resgate
from .resgates import _autorizar_loja


def _chave_lock_estorno(loja_id, identificador):
    digest = sha256(f'estorno-resgate:{loja_id}:{identificador}'.encode('utf-8')).digest()
    return int.from_bytes(digest[:8], byteorder='big', signed=True)


def _travar_chave_estorno(loja_id, identificador):
    if not connection.in_atomic_block:
        raise RuntimeError('O advisory lock de Estorno exige transação.')
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(%s)', [_chave_lock_estorno(loja_id, identificador)])


def estornar_resgate(*, credencial, loja_id, resgate_identificador_externo, identificador_externo):
    with transaction.atomic():
        loja = _autorizar_loja(credencial, loja_id)
        identificador = normalizar_identificador_resgate(identificador_externo)
        alvo = normalizar_identificador_resgate(resgate_identificador_externo)
        _travar_chave_estorno(loja.pk, identificador)
        existente = EstornoResgate.objects.select_related('resgate').filter(
            loja=loja, identificador_externo=identificador,
        ).first()
        if existente is not None:
            if existente.resgate.identificador_externo != alvo:
                raise IdempotenciaConflitante
            return existente, False
        resgate = Resgate.objects.filter(loja=loja, identificador_externo=alvo).first()
        if resgate is None:
            raise ResgateNaoEncontrado
        Cliente.objects.select_for_update(no_key=True).get(pk=resgate.cliente_id)
        if EstornoResgate.objects.filter(resgate=resgate).exists():
            raise ResgateJaEstornado
        politica = resolver_configuracao(loja.empresa)
        estorno = EstornoResgate(
            resgate=resgate, loja=loja, cliente_id=resgate.cliente_id,
            credencial_origem_id=credencial.pk, identificador_externo=identificador,
            devolve_pontos_aplicado=politica.devolver_pontos_ao_estornar_resgate,
            estornado_em=timezone.now(),
        )
        with _permitir_escrita_resgates(estorno):
            estorno.save(force_insert=True)
        return estorno, True
