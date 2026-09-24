"""Escrita de configuração restrita aos services transacionais de níveis."""
from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import ValidationError
from django.db import connection


_nivel_em_escrita = ContextVar('nivel_em_escrita', default=None)


@contextmanager
def _permitir_escrita_nivel(nivel):
    if not connection.in_atomic_block:
        raise RuntimeError('A configuração de níveis exige transação.')
    token = _nivel_em_escrita.set(nivel)
    try:
        yield
    finally:
        _nivel_em_escrita.reset(token)


def _exigir_escrita_nivel(nivel):
    if not connection.in_atomic_block or _nivel_em_escrita.get() is not nivel:
        raise ValidationError('Use os services de Gestão para configurar níveis.')
