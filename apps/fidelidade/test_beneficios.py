from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, Inexact, localcontext
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.empresas.parametros import PADROES_FIDELIDADE
from apps.empresas.models import ConfiguracaoFidelidadeEmpresa

from .beneficios import NivelBeneficios, avaliar_fidelidade_compra
from .niveis import criar_nivel, editar_nivel, classificar_cliente
from .models import LotePontos, NivelFidelidade, AplicacaoEfeitoEventoLote
from .eventos import criar_evento
from .test_resgates import DadosResgates

D = Decimal


class AvaliacaoBeneficiosTests(SimpleTestCase):
    def avaliar(
        self,
        *,
        niveis=None,
        progresso=D('1000'),
        dias=1,
        valor=D('200'),
        multiplicador=D('1'),
        resgate=D('0'),
        **politicas,
    ):
        agora = timezone.now()
        return avaliar_fidelidade_compra(
            valor=valor,
            politica=replace(PADROES_FIDELIDADE, **politicas),
            instante=agora,
            ultima_compra=agora - timedelta(days=dias) if dias is not None else None,
            progresso=progresso,
            niveis=(
                niveis
                if niveis is not None
                else [NivelBeneficios(1, 'A', D('0'), D('20'), D('5'))]
            ),
            multiplicador=multiplicador,
            desconto_resgate=resgate,
        )

    def test_beneficios_independentes_e_sem_beneficios(self):
        for bonus, desconto, pontos, valor in [
            ('0', '0', '200', '200'),
            ('20', '0', '240', '200'),
            ('0', '5', '200', '190'),
        ]:
            with self.subTest(bonus=bonus, desconto=desconto):
                r = self.avaliar(
                    niveis=[
                        NivelBeneficios(
                            1,
                            'Livre',
                            D('0'),
                            D(bonus),
                            D(desconto),
                        ),
                    ],
                )
                self.assertEqual(r.pontos_concedidos, D(pontos))
                self.assertEqual(r.valor_final, D(valor))
        self.assertIsNone(self.avaliar(niveis=[]).nivel_bonus)

    def test_atividade_limite_primeira_compra_e_suspensao(self):
        self.assertTrue(self.avaliar(dias=180).ativo_antes)
        self.assertFalse(self.avaliar(dias=181).ativo_antes)
        self.assertFalse(
            self.avaliar(dias=None, promocao_retorno_ativa=True).retorno,
        )
        self.assertEqual(self.avaliar(dias=181).bonus_nivel, D('20'))
        for politica, bonus in [
            ('SEM_BENEFICIOS_NIVEL', '0'),
            ('COM_BENEFICIOS_NIVEL', '20'),
        ]:
            r = self.avaliar(
                dias=181,
                inatividade_suspende_beneficios_nivel=True,
                beneficio_primeira_compra_apos_inatividade=politica,
            )
            self.assertEqual(r.bonus_nivel, D(bonus))
            self.assertEqual(r.nivel_anterior.id, 1)

    def test_primeira_compra_mantem_nivel_sem_promocao_de_retorno(self):
        resultado = self.avaliar(
            dias=None,
            progresso=D('0'),
            valor=D('100'),
            inatividade_suspende_beneficios_nivel=True,
            promocao_retorno_ativa=True,
            bonus_pontos_retorno_percentual=D('30'),
            desconto_retorno_percentual=D('10'),
        )
        self.assertFalse(resultado.ativo_antes)
        self.assertFalse(resultado.retorno)
        self.assertTrue(resultado.beneficios_nivel_aplicaveis)
        self.assertEqual(resultado.bonus_nivel, D('20'))
        self.assertEqual(resultado.desconto_nivel, D('5'))
        self.assertEqual(resultado.pontos_concedidos, D('120'))
        self.assertEqual(resultado.valor_final, D('95'))
        self.assertEqual(resultado.bonus_retorno, D('0'))
        self.assertEqual(resultado.desconto_retorno, D('0'))
        self.assertEqual(resultado.pontos_bonus_retorno, D('0'))

    def test_campanha_atinge_nivel_sem_reclassificar_pelos_bonus(self):
        niveis = [
            NivelBeneficios(1, 'Inicial', D('0'), D('0'), D('0')),
            NivelBeneficios(2, 'Intermediário', D('1000'), D('100'), D('20')),
            NivelBeneficios(3, 'Superior', D('1100'), D('50'), D('50')),
        ]
        dados = dict(
            niveis=niveis,
            progresso=D('850'),
            valor=D('100'),
            dias=181,
            modo_aplicacao_nivel='ATINGIDO_NA_COMPRA',
            base_calculo_pontos='LIQUIDO',
            promocao_retorno_ativa=True,
            bonus_pontos_retorno_percentual=D('100'),
        )
        sem_campanha = self.avaliar(**dados)
        self.assertEqual(sem_campanha.nivel_bonus.id, 1)
        resultado = self.avaliar(multiplicador=D('2'), **dados)
        self.assertEqual(resultado.pontos_base, D('100'))
        self.assertEqual(resultado.pontos_campanha, D('200'))
        self.assertEqual(resultado.nivel_anterior.id, 1)
        self.assertEqual(resultado.nivel_bonus.id, 2)
        self.assertEqual(resultado.desconto_nivel, D('0'))
        self.assertEqual(resultado.valor_final, D('100'))
        self.assertEqual(resultado.pontos_bonus_nivel, D('100'))
        self.assertEqual(resultado.pontos_bonus_retorno, D('100'))
        self.assertEqual(resultado.pontos_concedidos, D('400'))
        # 850 + 400 ultrapassa 1100; os bônus não escolhem o nível Superior.
        self.assertEqual(resultado.nivel_bonus.nome, 'Intermediário')

    def test_retorno_independente_e_desligado(self):
        for ativo in (False, True):
            for bonus, desconto in [('30', '0'), ('0', '10'), ('30', '10')]:
                r = self.avaliar(
                    niveis=[],
                    dias=181,
                    promocao_retorno_ativa=ativo,
                    bonus_pontos_retorno_percentual=D(bonus),
                    desconto_retorno_percentual=D(desconto),
                )
                self.assertEqual(r.bonus_retorno, D(bonus) if ativo else 0)
                self.assertEqual(
                    r.desconto_retorno,
                    D(desconto) if ativo else 0,
                )
        self.assertEqual(
            self.avaliar(
                dias=1,
                promocao_retorno_ativa=True,
                bonus_pontos_retorno_percentual=D('30'),
            ).bonus_retorno,
            0,
        )

    def test_descontos_ordem_resgate_e_bases(self):
        for modo, valor in [('ADITIVO', '170'), ('SEQUENCIAL', '171')]:
            r = self.avaliar(
                dias=181,
                promocao_retorno_ativa=True,
                desconto_retorno_percentual=D('10'),
                modo_combinacao_descontos_percentuais=modo,
            )
            self.assertEqual(r.valor_final, D(valor))
        for ordem, valor in [
            ('ANTES_DOS_DESCONTOS_PERCENTUAIS', '144.50'),
            ('DEPOIS_DOS_DESCONTOS_PERCENTUAIS', '140'),
        ]:
            for base in ('BRUTO', 'LIQUIDO'):
                r = self.avaliar(
                    dias=181,
                    promocao_retorno_ativa=True,
                    desconto_retorno_percentual=D('10'),
                    ordem_aplicacao_resgate=ordem,
                    resgate=D('30'),
                    base_calculo_pontos=base,
                )
                self.assertEqual(r.valor_final, D(valor))
                self.assertEqual(
                    r.pontos_base,
                    D('200') if base=='BRUTO' else D(valor),
                )
        for ordem in ('ANTES_DOS_DESCONTOS_PERCENTUAIS', 'DEPOIS_DOS_DESCONTOS_PERCENTUAIS'):
            self.assertEqual(
                self.avaliar(resgate=D('999'), ordem_aplicacao_resgate=ordem).valor_final,
                0,
            )
        r = self.avaliar(
            niveis=[NivelBeneficios(1, 'A', D('0'), D('0'), D('90'))],
            dias=181,
            promocao_retorno_ativa=True,
            desconto_retorno_percentual=D('80'),
        )
        self.assertEqual(r.valor_final, 0)

    def test_campanha_nivel_retorno_aditivos_e_contexto_decimal(self):
        with localcontext() as ctx:
            ctx.prec = 3
            ctx.traps[Inexact] = True
            r = self.avaliar(
                valor=D('100'),
                dias=181,
                multiplicador=D('2'),
                promocao_retorno_ativa=True,
                bonus_pontos_retorno_percentual=D('30'),
            )
        self.assertEqual(r.pontos_concedidos, D('250'))

    def test_atingido_sem_recursao_ou_desconto_retroativo(self):
        niveis = [
            NivelBeneficios(1, 'A', D('0'), D('0'), D('0')),
            NivelBeneficios(2, 'B', D('1000'), D('100'), D('20')),
            NivelBeneficios(3, 'C', D('1100'), D('50'), D('50')),
        ]
        r = self.avaliar(
            valor=D('100'),
            progresso=D('905'),
            niveis=niveis,
            modo_aplicacao_nivel='ATINGIDO_NA_COMPRA',
            base_calculo_pontos='LIQUIDO',
        )
        self.assertEqual(r.nivel_bonus.id, 2)
        self.assertEqual(r.nivel_anterior.id, 1)
        self.assertEqual(r.valor_final, D('100'))
        self.assertEqual(r.pontos_concedidos, D('200'))
        r = self.avaliar(
            valor=D('50'),
            progresso=D('905'),
            niveis=niveis,
            modo_aplicacao_nivel='ATINGIDO_NA_COMPRA',
            dias=181,
            promocao_retorno_ativa=True,
            bonus_pontos_retorno_percentual=D('100'),
        )
        self.assertEqual(r.nivel_bonus.id, 1)

    def test_percentuais_invalidos_e_arredondamento_financeiro(self):
        for valor in (D('-1'), D('101'), D('NaN'), D('Infinity'), D('1.00001'), 1.2):
            with self.subTest(valor=valor), self.assertRaises(ValidationError):
                self.avaliar(bonus_pontos_retorno_percentual=valor)
        r = self.avaliar(
            valor=D('.01'),
            niveis=[NivelBeneficios(1, 'A', D('0'), D('0'), D('50'))],
            base_calculo_pontos='LIQUIDO',
        )
        self.assertEqual(r.valor_final, D('.01'))


class PersistenciaBeneficiosTests(DadosResgates, TestCase):
    def test_historico_retry_e_nivel_preservados(self):
        criar_nivel(
            self.request(),
            nome='Inicial',
            pontos_minimos=D('0'),
            bonus_pontos_percentual=D('20'),
            desconto_percentual=D('5'),
        )
        lote = self.lote()
        self.assertEqual(lote.pontos_concedidos, D('120'))
        self.assertEqual(
            lote.beneficios_aplicados['resultado']['valor_final'],
            '95.00',
        )
        self.configurar(pontos_por_real=D('9'))
        with patch(
            'apps.fidelidade.services.avaliar_fidelidade_compra',
            side_effect=AssertionError('retry recalculou'),
        ):
            compra, criada = self.registrar(
                identificador_externo=lote.compra.identificador_externo,
                valor=D('100.00'),
            )
        self.assertFalse(criada)
        self.assertEqual(
            compra.lote_pontos.beneficios_aplicados,
            lote.beneficios_aplicados,
        )
        lote.save()  # Não consulta configuração atual para recalcular histórico.
        lote.beneficios_aplicados['resultado']['valor_final'] = '1.00'
        with self.assertRaises(ValidationError):
            lote.save()
        self.assertEqual(
            classificar_cliente(self.cliente).nivel.nome,
            'Inicial',
        )

    def test_rollback_snapshot_invalido(self):
        with patch(
            'apps.fidelidade.services.snapshot_beneficios',
            return_value={'versao':999},
        ), self.assertRaises(ValidationError):
            self.lote()
        self.assertFalse(LotePontos.objects.exists())

    def test_validacao_dos_models(self):
        for campo in ('bonus_pontos_percentual', 'desconto_percentual'):
            with self.assertRaises(ValidationError):
                criar_nivel(
                    self.request(),
                    nome='Inválido',
                    pontos_minimos=D('0'),
                    **{campo:D('101')},
                )
        cfg = ConfiguracaoFidelidadeEmpresa.objects.get(empresa=self.empresa)
        cfg.desconto_retorno_percentual = D('-1')
        with self.assertRaises(ValidationError):
            cfg.save()

    def test_fluxo_real_campanha_retorno_e_segunda_compra_ativa(self):
        self.lote(ocorrida_em=self.instante - timedelta(days=181))
        nivel = criar_nivel(
            self.request(),
            nome='Inicial',
            pontos_minimos=D('0'),
            bonus_pontos_percentual=D('20'),
            desconto_percentual=D('5'),
        )
        editar_nivel(
            self.request(),
            nivel.pk,
            nome='Inicial',
            pontos_minimos=D('0'),
        )
        nivel.refresh_from_db()
        self.assertEqual(nivel.bonus_pontos_percentual, D('20'))
        self.configurar(
            promocao_retorno_ativa=True,
            bonus_pontos_retorno_percentual=D('30'),
            desconto_retorno_percentual=D('10'),
            inatividade_suspende_beneficios_nivel=True,
            beneficio_primeira_compra_apos_inatividade='COM_BENEFICIOS_NIVEL',
        )
        criar_evento(
            self.request(),
            nome='Campanha real',
            escopo='EMPRESA',
            inicio_em=self.instante - timedelta(days=1),
            fim_em=self.instante + timedelta(days=1),
            efeitos=[{'tipo': 'MULTIPLICADOR_PONTOS', 'valor': D('2')}],
        )
        lote = self.lote()
        self.assertEqual(lote.pontos_concedidos, D('250'))
        self.assertEqual(
            lote.beneficios_aplicados['resultado']['valor_final'],
            '85.00',
        )
        self.assertTrue(
            AplicacaoEfeitoEventoLote.objects.filter(lote=lote).exists(),
        )
        seguinte = self.lote()
        self.assertFalse(seguinte.beneficios_aplicados['resultado']['retorno'])
        self.assertTrue(
            seguinte.beneficios_aplicados['resultado']['ativo_antes'],
        )
        self.assertEqual(seguinte.pontos_concedidos, D('220'))

    def test_constraints_sql_percentuais_com_savepoints(self):
        nivel = criar_nivel(self.request(), nome='Inicial', pontos_minimos=D('0'))
        cfg = ConfiguracaoFidelidadeEmpresa.objects.get(empresa=self.empresa)
        # Manager interno só no teste: demonstra a defesa SQL independentemente do service.
        for model, pk, campos in (
            (
                NivelFidelidade,
                nivel.pk,
                ('bonus_pontos_percentual', 'desconto_percentual'),
            ),
            (
                ConfiguracaoFidelidadeEmpresa,
                cfg.pk,
                (
                    'bonus_pontos_retorno_percentual',
                    'desconto_retorno_percentual',
                ),
            ),
        ):
            for campo in campos:
                for valor in (D('-0.0001'), D('100.0001')):
                    with self.subTest(campo=campo, valor=valor), self.assertRaises(IntegrityError):
                        with transaction.atomic():
                            model._base_manager.filter(pk=pk).update(
                                **{campo: valor},
                            )
        self.assertEqual(
            NivelFidelidade.objects.get(pk=nivel.pk).bonus_pontos_percentual,
            0,
        )
