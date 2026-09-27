class LojaForaDoEscopo(Exception):
    pass


class ClienteNaoEncontrado(Exception):
    pass


class IdempotenciaConflitante(Exception):
    pass


class PontosAbaixoDoMinimo(Exception):
    pass


class IncrementoResgateInvalido(Exception):
    pass


class SaldoInsuficiente(Exception):
    pass


class ResgateNaoEncontrado(Exception):
    pass


class ResgateJaEstornado(Exception):
    pass


class ResgateVinculadoCompra(Exception):
    pass


class LimiteResgateExcedido(Exception):
    pass
