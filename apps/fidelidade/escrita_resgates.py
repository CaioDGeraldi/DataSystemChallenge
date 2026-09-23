"""Escrita inicial exclusiva da operação atômica, como no histórico de Eventos."""
from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import ValidationError
from django.db import connection


_objetos_em_escrita = ContextVar('objetos_resgates_em_escrita', default=frozenset())


@contextmanager
def _permitir_escrita_resgates(*objetos):
    if not connection.in_atomic_block:
        raise RuntimeError('A emissão de Resgate exige transação.')
    token = _objetos_em_escrita.set(frozenset(id(objeto) for objeto in objetos))
    try:
        yield
    finally:
        _objetos_em_escrita.reset(token)


def _exigir_escrita_resgates(objeto):
    if not connection.in_atomic_block or id(objeto) not in _objetos_em_escrita.get():
        raise ValidationError('Use registrar_resgate para criar Resgate e suas alocações completas.')
