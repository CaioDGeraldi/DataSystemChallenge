from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, Inexact, localcontext
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase

from apps.empresas.parametros import PADROES_FIDELIDADE
from .beneficios import reavaliar_snapshot
from .calculos_resgate import maximo_desconto_compra, maximo_resgate, teto_resgate
from .estornos import estornar_resgate
from .exceptions import (
    IdempotenciaConflitante, LimiteResgateExcedido, ResgateJaEstornado,
    ResgateNaoEncontrado, ResgateVinculadoCompra,
)
from .models import Compra, LotePontos
from .niveis import criar_nivel
from .test_resgates import DadosResgates

D = Decimal


class MaximoResgateTests(SimpleTestCase):
    def test_capacidade_respeita_combinacao_e_fracoes_sem_arredondar_para_cima(self):
        for modo, capacidade, pontos in [('ADITIVO', '0', 0), ('SEQUENCIAL', '21', 420)]:
            politica = replace(PADROES_FIDELIDADE, limite_resgate_percentual=D('50'),
                               modo_combinacao_descontos_percentuais=modo,
                               resgate_minimo_pontos=1, incremento_resgate_pontos=1)
            self.assertEqual(maximo_desconto_compra(D('100'), politica, D('70'), D('30')), D(capacidade))
            self.assertEqual(maximo_resgate(D('2000'), politica, valor_compra=D('100'),
                                           desconto_nivel=D('70'), desconto_retorno=D('30'))[0], pontos)
        politica = replace(politica, valor_monetario_por_ponto=D('0.01'))
        self.assertEqual(maximo_resgate(D('2000'), politica, valor_compra=D('0.05'),
                                       desconto_nivel=D('70')), (1, D('0.01')))

    def test_saldo_minimo_incremento_conversao_teto_e_contexto_decimal(self):
        politica = replace(PADROES_FIDELIDADE, resgate_minimo_pontos=120,
                           incremento_resgate_pontos=50, limite_resgate_percentual=D('50'))
        for saldo, bruto, pontos, desconto in [
            ('119.9999', '100', 0, '0'), ('120', '100', 120, '6'),
            ('169.9999', '100', 120, '6'), ('9999', '17', 170, '8.50'),
            ('9999', '16.99', 120, '6'), ('9999', '11.99', 0, '0'),
        ]:
            with self.subTest(saldo=saldo, bruto=bruto), localcontext() as ctx:
                ctx.prec = 3
                ctx.traps[Inexact] = True
                self.assertEqual(maximo_resgate(D(saldo), politica, valor_compra=D(bruto)), (pontos, D(desconto)))
        self.assertEqual(teto_resgate(D('0.01'), D('50')), D('0.00'))
        self.assertEqual(maximo_resgate(D('9999'), replace(politica, limite_resgate_percentual=D('0'))), (0, D('0')))


class CompraResgateTests(DadosResgates, TestCase):
    def setUp(self):
        super().setUp()
        self.lote('2000')
        self.resgate, _ = self.resgatar(pontos=1000)
        self.configurar(limite_resgate_percentual=D('50'))

    def comprar(self, **dados):
        return self.registrar(valor=D('100'), resgate_identificador_externo='RESGATE-001', **dados)

    def estornar(self):
        return estornar_resgate(credencial=self.credencial, loja_id=self.loja.pk,
                               resgate_identificador_externo='RESGATE-001', identificador_externo='E1')

    def test_sem_resgate_e_com_resgate_historico_sem_comparar_datas(self):
        sem, _ = self.registrar(identificador_externo='SEM', valor=D('100'))
        self.assertIsNone(sem.resgate_id)
        self.configurar(valor_monetario_por_ponto=D('0.99'), base_calculo_pontos='LIQUIDO')
        compra, criada = self.comprar(ocorrida_em=self.instante - timedelta(days=1))
        self.assertTrue(criada)
        self.assertEqual(compra.valor, D('100'))
        self.assertEqual(compra.resgate_id, self.resgate.pk)
        self.assertEqual(compra.lote_pontos.pontos_concedidos, D('50'))
        self.assertEqual(compra.lote_pontos.beneficios_aplicados['desconto_resgate'], '50.00')
        self.assert_invariantes()

    def test_retry_preserva_vinculo_apos_configuracao_mudar(self):
        compra, _ = self.comprar()
        snapshot = deepcopy(compra.lote_pontos.beneficios_aplicados)
        self.configurar(limite_resgate_percentual=D('0'), pontos_por_real=D('9'))
        with patch('apps.fidelidade.services.avaliar_fidelidade_compra', side_effect=AssertionError):
            retry, criada = self.comprar()
        self.assertFalse(criada)
        self.assertEqual(retry.resgate_id, compra.resgate_id)
        self.assertEqual(retry.lote_pontos.beneficios_aplicados, snapshot)
        for alvo in (None, 'INEXISTENTE'):
            with self.assertRaises(IdempotenciaConflitante):
                self.registrar(valor=D('100'), resgate_identificador_externo=alvo)
        compra.resgate = None
        with self.assertRaises(ValidationError):
            compra.save()

    def test_uso_duplo_e_estorno_isolado_rejeitados(self):
        self.comprar()
        with self.assertRaises(ResgateVinculadoCompra):
            self.comprar(identificador_externo='SEGUNDA')
        with self.assertRaises(ResgateVinculadoCompra):
            self.estornar()
        self.assertEqual(Compra.objects.filter(resgate=self.resgate).count(), 1)

    def test_estornado_rejeitado(self):
        self.estornar()
        with self.assertRaises(ResgateJaEstornado):
            self.comprar()

    def test_loja_cliente_tenant_incorretos(self):
        for dados in ({'loja_id': self.segunda.pk}, {'cliente_cpf': self.outro_usuario.cpf}):
            with self.subTest(dados=dados), self.assertRaises(ResgateNaoEncontrado):
                self.comprar(**dados)
        credencial, _ = self.emitir(membro=self.outro_membro)
        with self.assertRaises(ResgateNaoEncontrado):
            self.comprar(credencial=credencial, loja_id=self.externa.pk, cliente_cpf=self.sem_vinculo.cpf)

    def test_teto_bruto_independe_de_ordem_e_base(self):
        criar_nivel(self.request(), nome='Inicial', pontos_minimos=D('0'), desconto_percentual=D('20'))
        for ordem, final in [('ANTES_DOS_DESCONTOS_PERCENTUAIS', '40'), ('DEPOIS_DOS_DESCONTOS_PERCENTUAIS', '30')]:
            for base in ('BRUTO', 'LIQUIDO'):
                with self.subTest(ordem=ordem, base=base), transaction.atomic():
                    self.configurar(ordem_aplicacao_resgate=ordem, base_calculo_pontos=base)
                    compra, _ = self.comprar()
                    resultado = compra.lote_pontos.beneficios_aplicados['resultado']
                    self.assertEqual(D(resultado['valor_final']), D(final))
                    self.assertEqual(compra.lote_pontos.pontos_base, D('50') if base == 'BRUTO' else D(final))
                    transaction.set_rollback(True)
        with self.assertRaises(LimiteResgateExcedido):
            self.registrar(valor=D('99.99'), resgate_identificador_externo='RESGATE-001')

    def test_resgate_com_campanha_bonus_nivel_e_retorno(self):
        from .eventos import criar_evento
        from .models import AplicacaoEfeitoEventoLote
        instante = self.instante + timedelta(days=181)
        self.configurar(
            base_calculo_pontos='LIQUIDO', promocao_retorno_ativa=True,
            bonus_pontos_retorno_percentual=D('30'), desconto_retorno_percentual=D('10'),
        )
        criar_nivel(self.request(), nome='Inicial', pontos_minimos=D('0'),
                    bonus_pontos_percentual=D('20'), desconto_percentual=D('5'))
        criar_evento(self.request(), nome='Dobro', escopo='EMPRESA',
                     inicio_em=instante - timedelta(days=1), fim_em=instante + timedelta(days=1),
                     efeitos=[{'tipo': 'MULTIPLICADOR_PONTOS', 'valor': D('2')}])
        compra, _ = self.comprar(ocorrida_em=instante)
        lote = compra.lote_pontos
        # 100 - 15% - 50 = 35; 35 × 2 + 35 × 20% + 35 × 30% = 87,50.
        self.assertEqual(lote.pontos_base, D('35'))
        self.assertEqual(lote.pontos_concedidos, D('87.50'))
        self.assertTrue(lote.beneficios_aplicados['resultado']['retorno'])
        self.assertTrue(AplicacaoEfeitoEventoLote.objects.filter(lote=lote).exists())

    def test_rollback_vinculo_se_lote_falha_e_unicidade_sql(self):
        with patch('apps.fidelidade.services._criar_lote_da_nova_compra', side_effect=ValidationError('falha')):
            with self.assertRaises(ValidationError):
                self.comprar()
        self.assertFalse(Compra.objects.filter(resgate=self.resgate).exists())
        self.comprar()
        outra, _ = self.registrar(identificador_externo='OUTRA')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Compra.objects.filter(pk=outra.pk).update(resgate=self.resgate)

    def test_snapshot_v1_continua_valido_e_v2_nao_aceita_desconto_adulterado(self):
        lote = LotePontos.objects.first()
        antigo = deepcopy(lote.beneficios_aplicados)
        antigo['versao'] = 1
        antigo.pop('desconto_resgate')
        antigo['politica'].pop('limite_resgate_percentual')
        avaliacao = reavaliar_snapshot(antigo, lote.compra.valor, lote.compra.ocorrida_em, lote.multiplicador_pontos_aplicado)
        self.assertEqual(avaliacao.pontos_concedidos, lote.pontos_concedidos)
        compra, _ = self.comprar()
        novo = deepcopy(compra.lote_pontos.beneficios_aplicados)
        self.assertEqual(reavaliar_snapshot(novo, compra.valor, compra.ocorrida_em, compra.lote_pontos.multiplicador_pontos_aplicado).pontos_base, D('50'))
        novo['desconto_resgate'] = '0.00'
        with self.assertRaises(ValidationError):
            reavaliar_snapshot(novo, compra.valor, compra.ocorrida_em, compra.lote_pontos.multiplicador_pontos_aplicado)
