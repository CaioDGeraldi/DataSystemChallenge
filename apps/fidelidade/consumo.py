"""Consumo efetivo atual; a validade dos Lotes é filtrada pelo chamador."""


def alocacoes_com_consumo_efetivo(alocacoes):
    """Somente estorno com snapshot True libera capacidade do Lote original."""
    return alocacoes.exclude(resgate__estorno__devolve_pontos_aplicado=True)
