from datetime import datetime, timedelta, timezone as datetime_timezone
from decimal import Decimal, Inexact, ROUND_DOWN, localcontext
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.empresas.models import ConfiguracaoFidelidadeEmpresa, OverrideFidelidadeLoja
from apps.empresas.services import desativar_credencial

from .calculos import calcular_expiracao, calcular_pontos
from .exceptions import IdempotenciaConflitante
from .models import Compra, LotePontos
from .test_compras import DadosCompras


class CalculoPontosTests(SimpleTestCase):
    def test_produto_exato_e_todas_politicas(self):
        self.assertEqual(calcular_pontos(Decimal('49.90'), Decimal('1.00'), 2, 'HALF_UP'),
                         (Decimal('49.9000'), Decimal('49.9000')))
        for precisao, modo, resultado in (
            (2, 'HALF_UP', '62.3800'), (2, 'DOWN', '62.3700'), (2, 'UP', '62.3800'),
            (0, 'HALF_UP', '62.0000'), (1, 'HALF_UP', '62.4000'), (4, 'HALF_UP', '62.3750'),
            (0, 'DOWN', '62.0000'), (0, 'UP', '63.0000'), (1, 'DOWN', '62.3000'),
            (1, 'UP', '62.4000'), (4, 'DOWN', '62.3750'), (4, 'UP', '62.3750'),
        ):
            with self.subTest(precisao=precisao, modo=modo):
                base, concedidos = calcular_pontos(Decimal('49.90'), Decimal('1.25'), precisao, modo)
                self.assertEqual(str(base), '62.3750')
                self.assertEqual(str(concedidos), resultado)

    def test_meio_exato_zero_e_up_sem_fracao_excedente(self):
        self.assertEqual(calcular_pontos(Decimal('0.01'), Decimal('0.50'), 2, 'HALF_UP')[1], Decimal('0.0100'))
        for modo in ('HALF_UP', 'DOWN', 'UP'):
            self.assertEqual(tuple(map(str, calcular_pontos(Decimal('49.90'), Decimal('0.00'), 2, modo))),
                             ('0.0000', '0.0000'))
        self.assertEqual(calcular_pontos(Decimal('2.00'), Decimal('1.00'), 0, 'UP')[1], Decimal('2.0000'))

    def test_extremos_e_independencia_do_contexto_decimal_do_chamador(self):
        with localcontext() as contexto:
            contexto.prec = 3
            contexto.rounding = ROUND_DOWN
            contexto.traps[Inexact] = True
            contexto.Emax = 5
            base, concedidos = calcular_pontos(Decimal('9999999999.99'), Decimal('9999999999.99'), 0, 'UP')
            self.assertEqual(str(base), '99999999999800000000.0001')
            self.assertEqual(str(concedidos), '99999999999800000001.0000')
            self.assertEqual(contexto.prec, 3)
        self.assertEqual(calcular_pontos(Decimal('0.01'), Decimal('0.01'), 4, 'HALF_UP')[0], Decimal('0.0001'))

    def test_entradas_invalidas_nao_sao_convertidas_ou_arredondadas(self):
        for numero in (1.25, 1, True, '1.25', None, Decimal('-0.01'), Decimal('NaN'), Decimal('sNaN'),
                       Decimal('Infinity'), Decimal('0.001'), Decimal('10000000000.00')):
            for posicao in (0, 1):
                valores = [Decimal('49.90'), Decimal('1.25')]
                valores[posicao] = numero
                with self.subTest(numero=numero, posicao=posicao), self.assertRaises(ValidationError):
                    calcular_pontos(*valores, 2, 'HALF_UP')
        for precisao, modo in ((3, 'HALF_UP'), (True, 'UP'), ('2', 'DOWN'), (2, 'half_up'), (2, [])):
            with self.assertRaises(ValidationError):
                calcular_pontos(Decimal('1.00'), Decimal('1.00'), precisao, modo)


class ValidadePontosTests(SimpleTestCase):
    def test_calendario_comum_fim_de_mes_e_bissexto(self):
        zona = ZoneInfo('America/Sao_Paulo')
        for data, meses, esperada in (
            ((2026, 9, 23), 12, (2027, 9, 23)),
            ((2027, 1, 31), 1, (2027, 2, 28)),
            ((2028, 1, 31), 1, (2028, 2, 29)),
            ((2028, 2, 29), 12, (2029, 2, 28)),
            ((2026, 12, 31), 2, (2027, 2, 28)),
        ):
            with self.subTest(data=data):
                inicio = datetime(*data, 10, 30, 12, 345, tzinfo=zona)
                resultado = calcular_expiracao(inicio, meses)
                self.assertEqual(resultado, datetime(*esperada, 10, 30, 12, 345, tzinfo=zona))
                self.assertTrue(timezone.is_aware(resultado))
                self.assertEqual(resultado.tzinfo, zona)

    def test_calendario_usa_data_local_e_nao_dia_utc_ou_timezone_ativo(self):
        instante = datetime(2027, 2, 1, 1, tzinfo=datetime_timezone.utc)
        with timezone.override('Asia/Tokyo'):
            resultado = calcular_expiracao(instante, 1)
        self.assertEqual(resultado.isoformat(), '2027-02-28T22:00:00-03:00')

    def test_overflow_de_ano_ou_conversao_utc_rejeitado(self):
        zona = ZoneInfo('America/Sao_Paulo')
        for instante, meses in (
            (datetime(9999, 9, 23, 10, tzinfo=zona), 12),
            (datetime(2026, 9, 23, 10, tzinfo=zona), 2147483647),
            (datetime(9999, 10, 31, 23, tzinfo=zona), 2),
        ):
            with self.subTest(instante=instante, meses=meses), self.assertRaises(ValidationError):
                calcular_expiracao(instante, meses)

    def test_tipos_invalidos_e_erros_inesperados_nao_mascarados(self):
        inicio = datetime(2026, 9, 23, tzinfo=datetime_timezone.utc)
        for data, meses in ((inicio.replace(tzinfo=None), 12), ('2026-09-23', 12),
                            (inicio, 0), (inicio, True), (inicio, 1.5)):
            with self.assertRaises(ValidationError):
                calcular_expiracao(data, meses)
        with patch('apps.fidelidade.calculos.monthrange', side_effect=RuntimeError('Falha simulada')):
            with self.assertRaises(RuntimeError):
                calcular_expiracao(inicio, 12)


class LotePontosTests(DadosCompras, TestCase):
    def configurar(self, **valores):
        config, _ = ConfiguracaoFidelidadeEmpresa.objects.get_or_create(empresa=self.empresa)
        for campo, valor in valores.items():
            setattr(config, campo, valor)
        config.save()
        return config

    def test_criacao_snapshots_override_e_configuracao_no_processamento(self):
        self.configurar(pontos_por_real=Decimal('2.00'), precisao_pontos=2,
                        modo_arredondamento_pontos='DOWN', validade_pontos_meses=24)
        OverrideFidelidadeLoja.objects.create(loja=self.loja, pontos_por_real=Decimal('1.25'))
        compra, criada = self.registrar(valor=Decimal('49.90'), ocorrida_em=self.instante.replace(year=2020))
        lote = LotePontos.objects.get()
        self.assertTrue(criada)
        self.assertEqual(lote.compra_id, compra.pk)
        self.assertEqual(lote.cliente_id, compra.cliente_id)
        self.assertEqual(lote.pontos_base, Decimal('62.3750'))
        self.assertEqual(lote.pontos_concedidos, Decimal('62.3700'))
        self.assertEqual(lote.pontos_por_real_aplicado, Decimal('1.25'))
        self.assertEqual(lote.precisao_pontos_aplicada, 2)
        self.assertEqual(lote.modo_arredondamento_aplicado, 'DOWN')
        self.assertEqual(lote.validade_pontos_meses_aplicada, 24)
        self.assertEqual(lote.adquiridos_em, compra.ocorrida_em)
        self.assertEqual(lote.expira_em, compra.ocorrida_em.replace(year=2022))
        self.assertGreater(lote.criado_em, lote.adquiridos_em)

    def test_zero_e_extremos_persistem_com_quatro_casas(self):
        for taxa, valor, base, concedidos in (
            ('0.00', '49.90', '0.0000', '0.0000'),
            ('9999999999.99', '9999999999.99', '99999999999800000000.0001', '99999999999800000001.0000'),
        ):
            self.configurar(pontos_por_real=Decimal(taxa), precisao_pontos=0, modo_arredondamento_pontos='UP')
            compra, _ = self.registrar(identificador_externo=taxa, valor=Decimal(valor))
            lote = LotePontos.objects.get(compra=compra)
            self.assertEqual((str(lote.pontos_base), str(lote.pontos_concedidos)), (base, concedidos))

    def test_cliente_exato_e_cross_tenant_mesmo_com_objeto_adulterado(self):
        compra, _ = self.registrar()
        valores = LotePontos.objects.values().get(compra=compra)
        valores.pop('id')
        for cliente in (self.outro_cliente, self.cliente_externo):
            with self.subTest(cliente=cliente.pk), self.assertRaises(ValidationError) as erro:
                candidato = LotePontos(**dict(valores, cliente_id=cliente.pk))
                candidato.compra = compra
                compra.cliente_id = cliente.pk  # A relação em memória não é fonte de verdade.
                candidato.clean()
            self.assertIn('cliente', erro.exception.message_dict)

    def test_validacao_de_tipos_valores_e_consistencia_do_snapshot(self):
        self.registrar()
        valores = LotePontos.objects.values().get()
        valores.pop('id')
        invalidos = {
            'pontos_base': [1.0, Decimal('-1'), Decimal('NaN'), Decimal('sNaN'), Decimal('0.00001'), Decimal('200.0000')],
            'pontos_concedidos': [1.0, Decimal('-1'), Decimal('Infinity'), Decimal('200.0000')],
            'pontos_por_real_aplicado': [1.0, Decimal('-1'), Decimal('0.001'), Decimal('2.00')],
            'precisao_pontos_aplicada': [True, 3, '2'],
            'modo_arredondamento_aplicado': ['INVALID'],
            'validade_pontos_meses_aplicada': [True, 0, 24],
            'adquiridos_em': [self.instante.replace(tzinfo=None), self.instante + timedelta(days=1)],
            'expira_em': [self.instante.replace(tzinfo=None), self.instante],
            'criado_em': [self.instante.replace(tzinfo=None)],
        }
        for campo, entradas in invalidos.items():
            for entrada in entradas:
                with self.subTest(campo=campo, entrada=entrada), self.assertRaises(ValidationError):
                    LotePontos(**dict(valores, **{campo: entrada})).clean()

    def test_constraints_sql_unicidade_e_protect(self):
        compra, _ = self.registrar()
        lote = LotePontos.objects.get()
        for campo, valor in (
            ('pontos_base', -1), ('pontos_concedidos', -1), ('pontos_por_real_aplicado', -1),
            ('precisao_pontos_aplicada', 3), ('modo_arredondamento_aplicado', 'INVALID'),
            ('validade_pontos_meses_aplicada', 0),
        ):
            with self.subTest(campo=campo), self.assertRaises(IntegrityError), transaction.atomic():
                LotePontos.objects.filter(pk=lote.pk).update(**{campo: valor})
        valores = LotePontos.objects.values().get()
        valores.pop('id')
        with self.assertRaises(ValidationError):
            LotePontos.objects.create(**valores)
        with self.assertRaises(IntegrityError), transaction.atomic():
            LotePontos.objects.bulk_create([LotePontos(**valores)])
        for objeto in (compra, self.cliente):
            with self.assertRaises(ProtectedError):
                objeto.delete()
        self.assertEqual(LotePontos._meta.get_field('cliente').remote_field.on_delete.__name__, 'PROTECT')

    def test_todos_fatos_imutaveis_inclusive_update_fields_e_instancia_reconstruida(self):
        compra, _ = self.registrar()
        outra_compra, _ = self.registrar(identificador_externo='OUTRA')
        lote = LotePontos.objects.get(compra=compra)
        antes = LotePontos.objects.values().get(pk=lote.pk)
        alteracoes = {
            'compra': outra_compra, 'cliente': self.outro_cliente,
            'pontos_base': Decimal('2.0000'), 'pontos_concedidos': Decimal('2.0000'),
            'pontos_por_real_aplicado': Decimal('2.00'), 'precisao_pontos_aplicada': 4,
            'modo_arredondamento_aplicado': 'UP', 'validade_pontos_meses_aplicada': 24,
            'adquiridos_em': lote.adquiridos_em + timedelta(seconds=1),
            'expira_em': lote.expira_em + timedelta(seconds=1),
            'criado_em': lote.criado_em + timedelta(seconds=1),
        }
        for campo, valor in alteracoes.items():
            for metodo in ('clean', 'full_clean', 'save', 'parcial', 'reconstruida'):
                with self.subTest(campo=campo, metodo=metodo):
                    candidato = LotePontos(**antes) if metodo == 'reconstruida' else lote
                    setattr(candidato, campo, valor)
                    with self.assertRaises(ValidationError) as erro:
                        if metodo == 'parcial':
                            candidato.save(update_fields=['pontos_base'])
                        elif metodo == 'reconstruida':
                            candidato.save()
                        else:
                            getattr(candidato, metodo)()
                    self.assertIn(campo, erro.exception.message_dict)
                    self.assertEqual(LotePontos.objects.values().get(pk=lote.pk), antes)
                    lote.refresh_from_db()

    def test_historico_valido_apos_mudanca_de_configuracao_e_desativacao(self):
        compra, _ = self.registrar()
        lote = LotePontos.objects.get(compra=compra)
        antes = LotePontos.objects.values().get()
        self.configurar(pontos_por_real=Decimal('9.00'), precisao_pontos=0, modo_arredondamento_pontos='UP')
        desativar_credencial(self.request(), self.credencial.pk)
        lote.full_clean()
        lote.save()
        lote.save(update_fields=['pontos_base'])
        self.assertEqual(LotePontos.objects.values().get(), antes)

    def test_retry_outra_credencial_apos_mudancas_nao_resolve_nem_recalcula(self):
        compra, _ = self.registrar()
        antes = LotePontos.objects.values().get()
        self.configurar(pontos_por_real=Decimal('9.00'), validade_pontos_meses=2147483647)
        outra, _ = self.emitir()
        desativar_credencial(self.request(), self.credencial.pk)
        with patch('apps.fidelidade.services.resolver_configuracao', side_effect=AssertionError('Retry não resolve')):
            retry, criada = self.registrar(credencial=outra)
        self.assertFalse(criada)
        self.assertEqual(retry.pk, compra.pk)
        self.assertEqual(retry.lote_pontos.pk, antes['id'])
        self.assertEqual(LotePontos.objects.values().get(), antes)

    def test_conflito_preserva_lote(self):
        self.registrar()
        antes = list(LotePontos.objects.values())
        with self.assertRaises(IdempotenciaConflitante):
            self.registrar(valor=Decimal('200.00'))
        self.assertEqual(list(LotePontos.objects.values()), antes)

    def test_falha_ao_salvar_lote_faz_rollback_inclusive_se_falhar_apos_insert(self):
        original = LotePontos.save

        def salvar_e_falhar(lote, *args, **kwargs):
            original(lote, *args, **kwargs)
            raise ValidationError('Falha simulada')

        for falha in (ValidationError('Falha simulada'), IntegrityError('Falha não relacionada'), salvar_e_falhar):
            with patch.object(LotePontos, 'save', side_effect=falha, autospec=True):
                with self.assertRaises((ValidationError, IntegrityError)):
                    self.registrar()
            self.assertFalse(Compra.objects.exists())
            self.assertFalse(LotePontos.objects.exists())

    def test_expiracao_impossivel_rollback_sem_invalidar_configuracao_global(self):
        config = self.configurar(validade_pontos_meses=2147483647)
        config.full_clean()
        with self.assertRaises(ValidationError):
            self.registrar()
        self.assertFalse(Compra.objects.exists())
        self.assertFalse(LotePontos.objects.exists())
        self.configurar(validade_pontos_meses=12)
        with self.assertRaises(ValidationError):
            self.registrar(ocorrida_em=self.instante.replace(year=9999))
        self.assertFalse(Compra.objects.exists())
        self.assertFalse(LotePontos.objects.exists())

    def test_legado_sem_lote_nao_calcula_expiracao(self):
        compra = self.model(ocorrida_em=self.instante.replace(year=9999))
        compra.save()  # Representa registro anterior à concessão pelo service.
        self.configurar(validade_pontos_meses=2147483647)
        with patch('apps.fidelidade.services._criar_lote_da_nova_compra', side_effect=AssertionError('Sem backfill')):
            retry, criada = self.registrar(ocorrida_em=compra.ocorrida_em)
        self.assertFalse(criada)
        self.assertEqual(retry.pk, compra.pk)
        self.assertEqual(Compra.objects.count(), 1)
        self.assertFalse(LotePontos.objects.exists())
