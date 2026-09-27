"""Projeção pública do histórico; não consulta política atual nem expõe o snapshot."""
from decimal import Context, Decimal, localcontext


def explicar_compra(compra):
    lote = getattr(compra, 'lote_pontos', None)
    snapshot = lote.beneficios_aplicados if lote else None
    if not snapshot:
        # Legado não contém evidência suficiente para reconstruir benefícios.
        return None
    r = snapshot['resultado']
    with localcontext(Context(prec=60)):
        valores = {
            'bruto': format(compra.valor, '.2f'),
            'desconto_total': format(compra.valor - Decimal(r['valor_final']), '.2f'),
            'final': format(Decimal(r['valor_final']), '.2f'),
            'elegivel_pontos': format(Decimal(r['valor_elegivel_pontos']), '.2f'),
        }
    return {
        'valores': valores,
        'pontos': {
            publico: format(Decimal(r[interno]), '.4f')
            for publico, interno in (
                ('base', 'pontos_base'), ('apos_campanha', 'pontos_campanha'),
                ('bonus_nivel', 'pontos_bonus_nivel'), ('bonus_retorno', 'pontos_bonus_retorno'),
                ('total', 'pontos_concedidos'),
            )
        },
        'beneficios': {
            'nivel_desconto': r['nivel_anterior']['nome'] if r['nivel_anterior'] else None,
            'nivel_bonus': r['nivel_bonus']['nome'] if r['nivel_bonus'] else None,
            'beneficios_nivel_aplicaveis': r['beneficios_nivel_aplicaveis'],
            'retorno': r['retorno'],
            **{campo: format(Decimal(r[origem]), '.4f') for campo, origem in (
                ('bonus_nivel_percentual', 'bonus_nivel'), ('desconto_nivel_percentual', 'desconto_nivel'),
                ('bonus_retorno_percentual', 'bonus_retorno'), ('desconto_retorno_percentual', 'desconto_retorno'),
            )},
            'multiplicador_campanha': format(lote.multiplicador_pontos_aplicado, '.4f'),
            'ordem_aplicacao_resgate': snapshot['politica']['ordem_aplicacao_resgate'],
            'base_calculo_pontos': snapshot['politica']['base_calculo_pontos'],
        },
    }
