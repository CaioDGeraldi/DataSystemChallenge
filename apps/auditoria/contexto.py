from contextlib import contextmanager

from django.db import DEFAULT_DB_ALIAS, connections, transaction

from .models import EventoAuditoria


CHAVES = (
    "retorna.auditoria_origem",
    "retorna.auditoria_usuario_id",
    "retorna.auditoria_credencial_id",
)


@contextmanager
def contexto_auditoria(*, origem=None, usuario_id=None, credencial_id=None, using=DEFAULT_DB_ALIAS):
    """Disponibiliza ator/origem somente durante este escopo transacional.

    Abre atomic mesmo sem ATOMIC_REQUESTS. Em aninhamento, cria um savepoint:
    exceções restauram os SET LOCAL pelo rollback, sem queries em transação
    quebrada. Na saída normal, restaura os valores lidos do próprio banco.

    GUCs customizadas representam ausência por string vazia após restauração;
    leitores devem usar NULLIF(current_setting(chave, true), '').
    """
    if origem is not None and origem not in EventoAuditoria.Origem.values:
        raise ValueError("Origem de auditoria inválida.")

    valores = (origem, usuario_id, credencial_id)
    conexao = connections[using]
    with transaction.atomic(using=using):
        with conexao.cursor() as cursor:
            anteriores = []
            for chave, valor in zip(CHAVES, valores):
                cursor.execute("SELECT current_setting(%s, true)", [chave])
                anteriores.append(cursor.fetchone()[0])
                cursor.execute("SELECT set_config(%s, %s, true)", [
                    chave, "" if valor is None else str(valor),
                ])

        yield

        # Sem finally: uma exceção deve chegar intacta ao atomic/rollback.
        # Um rollback marcado explicitamente também restaura via savepoint.
        if not conexao.needs_rollback:
            with conexao.cursor() as cursor:
                for chave, anterior in zip(CHAVES, anteriores):
                    cursor.execute("SELECT set_config(%s, %s, true)", [
                        chave, "" if anterior is None else anterior,
                    ])
