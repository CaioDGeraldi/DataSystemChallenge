from contextlib import ExitStack
from datetime import timedelta
from decimal import Context, Decimal, Inexact, ROUND_DOWN, ROUND_HALF_UP, localcontext
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.db.models.deletion import ProtectedError
from django.test import SimpleTestCase, TestCase

from apps.empresas.models import ConfiguracaoFidelidadeEmpresa
from apps.empresas.services import desativar_credencial

from .calculos_resgate import MAX_PONTOS_RESGATE, calcular_desconto, validar_pontos_solicitados
from .escrita_resgates import _permitir_escrita_resgates
from .eventos import cancelar_evento, criar_evento
from .exceptions import (
    ClienteNaoEncontrado, IdempotenciaConflitante, IncrementoResgateInvalido,
    LojaForaDoEscopo, PontosAbaixoDoMinimo, SaldoInsuficiente,
)
from .consumo import alocacoes_com_consumo_efetivo
from .models import AlocacaoResgate, AplicacaoEfeitoEventoLote, Compra, LotePontos, Resgate
from .resgates import registrar_resgate
from .services import registrar_compra
from .test_compras import DadosCompras


class DadosResgates(DadosCompras):
    def setUp(self):
        super().setUp()
        self.configurar(resgate_minimo_pontos=100, incremento_resgate_pontos=50,
                        pontos_por_real=Decimal('1.00'), precisao_pontos=4,
                        valor_monetario_por_ponto=Decimal('0.05'))

    def configurar(self, **valores):
        config, _ = ConfiguracaoFidelidadeEmpresa.objects.get_or_create(empresa=self.empresa)
        for campo, valor in valores.items():
            setattr(config, campo, valor)
        config.save()
        return config

    def lote(self, valor='100.00', **alteracoes):
        dados = dict(credencial=self.credencial, loja_id=self.loja.pk,
                     cliente_cpf=self.usuario.cpf, identificador_externo=f'COMPRA-{Compra.objects.count()}',
                     valor=Decimal(valor), ocorrida_em=self.instante)
        dados.update(alteracoes)
        compra, _ = registrar_compra(**dados)
        return compra.lote_pontos

    def resgatar(self, **alteracoes):
        dados = dict(credencial=self.credencial, loja_id=self.loja.pk,
                     cliente_cpf=self.usuario.cpf, identificador_externo='RESGATE-001', pontos=100)
        dados.update(alteracoes)
        with patch('apps.fidelidade.resgates.timezone.now', return_value=self.instante):
            return registrar_resgate(**dados)

    def assert_invariantes(self):
        for resgate in Resgate.objects.all():
            self.assertEqual(resgate.alocacoes.aggregate(total=Sum('pontos_consumidos'))['total'],
                             resgate.pontos_resgatados)
        for lote in LotePontos.objects.all():
            total = alocacoes_com_consumo_efetivo(lote.alocacoes_resgate.all()).aggregate(total=Sum('pontos_consumidos'))['total'] or Decimal('0')
            self.assertLessEqual(total, lote.pontos_concedidos)


class CalculoResgateTests(SimpleTestCase):
    def test_limites_fisicos_contexto_independente_e_half_up_financeiro(self):
        with localcontext() as contexto:
            contexto.prec = 3
            contexto.rounding = ROUND_DOWN
            contexto.traps[Inexact] = True
            contexto.Emax = 5
            with patch('apps.fidelidade.calculos_resgate.Context', wraps=Context) as fabrica:
                resultado = calcular_desconto(Decimal(MAX_PONTOS_RESGATE), Decimal('9999999999.99'))
            fabrica.assert_called_once_with(prec=40, rounding=ROUND_HALF_UP)
            self.assertEqual(str(resultado), '999999999998999999990000000000.01')
            self.assertEqual(contexto.prec, 3)
        self.assertEqual(str(calcular_desconto(Decimal('200'), Decimal('0.05'))), '10.00')
        # Inteiro × taxa de duas casas já é exato em centavos: não há meia fração
        # de centavo válida no contrato. Não aceitar .005 para simular um empate.
        with self.assertRaises(ValidationError):
            calcular_desconto(Decimal('1'), Decimal('0.005'))

    def test_quantidade_solicitada_estrita_e_teto(self):
        for valor in (0, -1, True, 100.0, '100', Decimal('100'), None, MAX_PONTOS_RESGATE + 1):
            with self.subTest(valor=valor), self.assertRaises(ValidationError):
                validar_pontos_solicitados(valor)
        self.assertEqual(validar_pontos_solicitados(MAX_PONTOS_RESGATE), Decimal(MAX_PONTOS_RESGATE))

    def test_financeiro_nao_trunca_nem_converte_tipos_e_nao_finitos(self):
        for pontos, taxa in (
            (Decimal('1.5'), Decimal('.05')), (Decimal(10**20), Decimal('.05')),
            (Decimal('100'), Decimal('10000000000.00')),
        ):
            with self.assertRaises(ValidationError):
                calcular_desconto(pontos, taxa)
        for valor in (None, True, 1, 1.0, '1', Decimal('0'), Decimal('-1'),
                      Decimal('NaN'), Decimal('sNaN'), Decimal('Infinity')):
            for posicao in (0, 1):
                argumentos = [Decimal('100'), Decimal('.05')]
                argumentos[posicao] = valor
                with self.subTest(valor=valor, posicao=posicao), self.assertRaises(ValidationError):
                    calcular_desconto(*argumentos)


class ResgateDominioTests(DadosResgates, TestCase):
    def test_lote_unico_saldo_exato_instante_unico_e_snapshots(self):
        lote = self.lote('200.00')
        antes = LotePontos.objects.values().get(pk=lote.pk)
        with patch('apps.fidelidade.resgates.timezone.now', return_value=self.instante) as agora:
            resgate, criado = registrar_resgate(credencial=self.credencial, loja_id=self.loja.pk,
                cliente_cpf=self.usuario.cpf, identificador_externo='UNICO', pontos=200)
        agora.assert_called_once_with()
        self.assertTrue(criado)
        resgate.refresh_from_db()
        self.assertEqual(resgate.pontos_resgatados, Decimal('200'))
        self.assertEqual(resgate.resgatado_em, self.instante)
        self.assertEqual((resgate.resgate_minimo_pontos_aplicado, resgate.incremento_resgate_pontos_aplicado,
                          resgate.valor_monetario_por_ponto_aplicado, resgate.valor_desconto),
                         (100, 50, Decimal('.05'), Decimal('10.00')))
        self.assertEqual(list(resgate.alocacoes.values_list('lote_id', 'pontos_consumidos')),
                         [(lote.pk, Decimal('200.0000'))])
        self.assertEqual(LotePontos.objects.values().get(pk=lote.pk), antes)
        self.assert_invariantes()

    def test_multiplos_lotes_fefo_expiracao_antes_de_pk(self):
        posterior = self.lote('80.00')
        anterior = self.lote('40.00', ocorrida_em=self.instante - timedelta(days=10))
        resgate, _ = self.resgatar()
        self.assertEqual(list(resgate.alocacoes.order_by('pk').values_list('lote_id', 'pontos_consumidos')),
                         [(anterior.pk, Decimal('40')), (posterior.pk, Decimal('60'))])
        self.assert_invariantes()

    def test_fefo_desempate_aquisicao_antes_de_pk(self):
        # Mesma expiração por políticas históricas de validade distintas.
        novo = self.lote(ocorrida_em=self.instante.replace(month=8))
        self.configurar(validade_pontos_meses=13)
        antigo = self.lote(ocorrida_em=self.instante.replace(month=7))
        self.assertEqual(novo.expira_em, antigo.expira_em)
        resgate, _ = self.resgatar()
        self.assertEqual(resgate.alocacoes.get().lote_id, antigo.pk)

    def test_fefo_desempate_pk(self):
        primeiro = self.lote()
        segundo = self.lote()
        self.assertEqual(primeiro.expira_em, segundo.expira_em)
        self.assertEqual(primeiro.adquiridos_em, segundo.adquiridos_em)
        resgate, _ = self.resgatar()
        self.assertEqual(resgate.alocacoes.get().lote_id, primeiro.pk)

    def test_expiracao_estrita_e_aquisicao_futura_persistida(self):
        expirado = self.lote(ocorrida_em=self.instante.replace(year=2024))
        limite = self.lote(ocorrida_em=self.instante.replace(year=2025))
        self.assertEqual(limite.expira_em, self.instante)
        with self.assertRaises(SaldoInsuficiente):
            self.resgatar()
        futuro = self.lote(ocorrida_em=self.instante + timedelta(days=1))
        resgate, _ = self.resgatar()
        self.assertEqual(resgate.alocacoes.get().lote_id, futuro.pk)
        self.assertFalse(AlocacaoResgate.objects.filter(lote__in=[expirado, limite]).exists())

    def test_minimo_incremento_validos_e_invalidos(self):
        self.lote('1000.00')
        for pontos, erro in ((99, PontosAbaixoDoMinimo), (101, IncrementoResgateInvalido),
                             (125, IncrementoResgateInvalido)):
            with self.assertRaises(erro):
                self.resgatar(pontos=pontos)
        self.assertFalse(Resgate.objects.exists())
        for pontos in (100, 150, 200, 250):
            self.assertTrue(self.resgatar(pontos=pontos, identificador_externo=str(pontos))[1])
        self.assert_invariantes()

    def test_incremento_e_deslocado_do_minimo(self):
        self.configurar(resgate_minimo_pontos=125, incremento_resgate_pontos=50)
        self.lote('500.00')
        self.resgatar(pontos=125)
        self.resgatar(pontos=175, identificador_externo='175')
        with self.assertRaises(IncrementoResgateInvalido):
            self.resgatar(pontos=150, identificador_externo='150')

    def test_saldo_anterior_fracionario_e_consumo_fracionario_exato(self):
        a = self.lote('99.75')
        b = self.lote('50.50')
        antes = list(LotePontos.objects.order_by('pk').values())
        resgate, _ = self.resgatar()
        self.assertEqual(list(resgate.alocacoes.order_by('pk').values_list('lote_id', 'pontos_consumidos')),
                         [(a.pk, Decimal('99.7500')), (b.pk, Decimal('.2500'))])
        with self.assertRaises(SaldoInsuficiente):
            self.resgatar(identificador_externo='SEM-SALDO')
        self.configurar(resgate_minimo_pontos=1, incremento_resgate_pontos=1)
        self.resgatar(pontos=50, identificador_externo='RESIDUAL')
        with self.assertRaises(SaldoInsuficiente):
            self.resgatar(pontos=1, identificador_externo='FRACAO')
        self.assertEqual(list(LotePontos.objects.order_by('pk').values()), antes)
        self.assert_invariantes()

    def test_saldo_zero_ou_fracao_abaixo_do_minimo_nao_cria_historico(self):
        self.lote('99.99')
        with self.assertRaises(SaldoInsuficiente):
            self.resgatar()
        self.assertFalse(Resgate.objects.exists())
        self.assertFalse(AlocacaoResgate.objects.exists())

    def test_quatro_casas_e_contexto_decimal_restrito_na_operacao_completa(self):
        self.configurar(pontos_por_real=Decimal('.01'))
        primeiro = self.lote('9999.99')
        segundo = self.lote('.01')
        with localcontext() as contexto:
            contexto.prec = 3
            contexto.rounding = ROUND_DOWN
            contexto.traps[Inexact] = True
            resgate, _ = self.resgatar()
        self.assertEqual(list(resgate.alocacoes.order_by('pk').values_list('lote_id', 'pontos_consumidos')),
                         [(primeiro.pk, Decimal('99.9999')), (segundo.pk, Decimal('.0001'))])
        self.assert_invariantes()

    def test_lote_zero_nao_gera_alocacao(self):
        self.configurar(pontos_por_real=Decimal('0'))
        zero = self.lote()
        self.configurar(pontos_por_real=Decimal('1'))
        positivo = self.lote()
        resgate, _ = self.resgatar()
        self.assertEqual(resgate.alocacoes.get().lote_id, positivo.pk)
        self.assertFalse(zero.alocacoes_resgate.exists())

    def test_retry_historico_apos_expiracao_configuracao_e_origem_inativa(self):
        self.lote()
        resgate, _ = self.resgatar()
        antes = Resgate.objects.values().get()
        alocacoes = list(AlocacaoResgate.objects.values())
        outra, _ = self.emitir('LOJAS', [self.loja])
        self.configurar(resgate_minimo_pontos=999, incremento_resgate_pontos=999,
                        valor_monetario_por_ponto=Decimal('9.99'))
        desativar_credencial(self.request(), self.credencial.pk)
        self.instante += timedelta(days=800)
        with ExitStack() as stack:
            for alvo in ('resolver_configuracao', 'calcular_desconto', '_selecionar_lotes_fefo',
                         '_calcular_saldo', '_criar_alocacoes'):
                stack.enter_context(patch(f'apps.fidelidade.resgates.{alvo}', side_effect=AssertionError(alvo)))
            stack.enter_context(patch.object(Resgate, 'save', side_effect=AssertionError('Retry não salva')))
            retry, criado = self.resgatar(credencial=outra, identificador_externo=' RESGATE-001 ',
                                         cliente_cpf='529.982.247-25')
        self.assertFalse(criado)
        self.assertEqual(retry.pk, resgate.pk)
        self.assertEqual(Resgate.objects.values().get(), antes)
        self.assertEqual(list(AlocacaoResgate.objects.values()), alocacoes)
        retry.full_clean()
        retry.save(update_fields=['valor_desconto'])
        retry.alocacoes.get().save()
        self.assertEqual(Resgate.objects.values().get(), antes)

    def test_conflitos_e_chave_por_loja_case_e_normalizacao(self):
        self.lote('1000.00')
        resgate, _ = self.resgatar(identificador_externo='  Venda  A-b \t')
        self.assertEqual(resgate.identificador_externo, 'Venda  A-b')
        for alteracoes in ({'cliente_cpf': self.outro_usuario.cpf}, {'pontos': 150}):
            with self.assertRaises(IdempotenciaConflitante):
                self.resgatar(identificador_externo='Venda  A-b', **alteracoes)
        for alteracoes in ({'identificador_externo': 'venda  A-b'},
                           {'identificador_externo': 'Venda  A-b', 'loja_id': self.segunda.pk},
                           {'identificador_externo': ' ' + 'A' * 255 + ' '}):
            self.assertTrue(self.resgatar(**alteracoes)[1])
        for valor in ('', ' \t', 'a' * 256, 123, None):
            with self.assertRaises(ValidationError):
                self.resgatar(identificador_externo=valor)
        self.assert_invariantes()

    def test_autorizacao_antes_do_advisory_e_cliente_sem_vinculo(self):
        restrita, _ = self.emitir('LOJAS', [self.loja])
        restrita.escopo = 'EMPRESA'
        with patch('apps.fidelidade.resgates._travar_chave_resgate', side_effect=AssertionError('Sem autorização')):
            for credencial, loja in ((self.credencial, self.externa), (restrita, self.segunda)):
                with self.assertRaises(LojaForaDoEscopo):
                    self.resgatar(credencial=credencial, loja_id=loja.pk)
            with self.assertRaises(LojaForaDoEscopo):
                self.resgatar(loja_id=999999)
        for cpf in (self.sem_vinculo.cpf, '39053344705'):
            with self.assertRaises(ClienteNaoEncontrado):
                self.resgatar(cliente_cpf=cpf)
        self.assertFalse(Resgate.objects.exists())

    def test_rollback_apos_insert_de_alocacao_e_helper_incompleto(self):
        self.lote('60.00')
        self.lote('60.00')
        salvar = AlocacaoResgate.save

        def falhar_apos_segunda(alocacao, *args, **kwargs):
            salvar(alocacao, *args, **kwargs)
            if AlocacaoResgate.objects.count() == 2:
                raise ValidationError('Falha depois do segundo INSERT')

        with patch.object(AlocacaoResgate, 'save', falhar_apos_segunda):
            with self.assertRaises(ValidationError):
                self.resgatar()
        self.assertFalse(Resgate.objects.exists())
        self.assertFalse(AlocacaoResgate.objects.exists())
        with patch('apps.fidelidade.resgates._criar_alocacoes', return_value=None):
            with self.assertRaises(ValidationError):
                self.resgatar()
        self.assertFalse(Resgate.objects.exists())
        self.assertTrue(self.resgatar()[1])  # Conexão/transação continuam utilizáveis.

    def test_rollback_financeiro_e_integridade_inesperada(self):
        self.lote()
        for alvo, erro in (('calcular_desconto', ValidationError('Não representável')),
                           ('Resgate.save', IntegrityError('Outra constraint'))):
            with patch(f'apps.fidelidade.resgates.{alvo}', side_effect=erro):
                with self.assertRaises(type(erro)):
                    self.resgatar()
            self.assertFalse(Resgate.objects.exists())
            self.assertFalse(AlocacaoResgate.objects.exists())

    def test_campanha_consome_concedidos_sem_recalcular_compra_ou_evento(self):
        evento = criar_evento(self.request(), nome='2x', inicio_em=self.instante - timedelta(days=1),
            fim_em=self.instante + timedelta(days=1), escopo='EMPRESA',
            efeitos=[{'tipo': 'MULTIPLICADOR_PONTOS', 'valor': Decimal('2.0000')}])
        lote = self.lote()
        self.assertEqual((lote.pontos_base, lote.pontos_concedidos), (Decimal('100'), Decimal('200')))
        antes = AplicacaoEfeitoEventoLote.objects.values().get()
        cancelar_evento(self.request(), evento.pk)
        with patch('apps.fidelidade.services.resolver_efeito_evento', side_effect=AssertionError('Sem recálculo')):
            resgate, _ = self.resgatar(pontos=200)
            compra, criada = registrar_compra(**self.dados(identificador_externo=lote.compra.identificador_externo,
                                                         valor=Decimal('100.00')))
        self.assertFalse(criada)
        self.assertEqual(compra.lote_pontos.pk, lote.pk)
        self.assertEqual(resgate.alocacoes.get().pontos_consumidos, Decimal('200'))
        self.assertEqual(AplicacaoEfeitoEventoLote.objects.values().get(), antes)


class HistoricoResgateTests(DadosResgates, TestCase):
    def setUp(self):
        super().setUp()
        self.lote('300.00')
        self.resgate, _ = self.resgatar()
        self.alocacao = self.resgate.alocacoes.get()

    def test_imutabilidade_todos_campos_inclusive_instancia_antiga_e_update_fields(self):
        alteracoes = {
            Resgate: dict(loja_id=self.segunda.pk, cliente_id=self.outro_cliente.pk,
                credencial_origem_id=self.emitir()[0].pk, identificador_externo='OUTRO',
                pontos_resgatados=Decimal('150'), resgate_minimo_pontos_aplicado=50,
                incremento_resgate_pontos_aplicado=25, valor_monetario_por_ponto_aplicado=Decimal('.10'),
                valor_desconto=Decimal('10.00'), resgatado_em=self.instante + timedelta(seconds=1)),
            AlocacaoResgate: dict(resgate_id=self.resgatar(identificador_externo='SEGUNDO')[0].pk,
                                 lote_id=self.lote().pk, pontos_consumidos=Decimal('1')),
        }
        for objeto in (self.resgate, self.alocacao):
            modelo = type(objeto)
            antes = modelo.objects.values().get(pk=objeto.pk)
            for campo, valor in alteracoes[modelo].items():
                for metodo in ('clean', 'full_clean', 'save', 'parcial'):
                    candidato = modelo(**dict(antes, **{campo: valor}))
                    with self.subTest(modelo=modelo, campo=campo, metodo=metodo), self.assertRaises(ValidationError):
                        if metodo == 'parcial':
                            candidato.save(update_fields=['pontos_resgatados' if modelo is Resgate else 'pontos_consumidos'])
                        else:
                            getattr(candidato, metodo)()
                    self.assertEqual(modelo.objects.values().get(pk=objeto.pk), antes)
            objeto.save()
            self.assertEqual(modelo.objects.values().get(pk=objeto.pk), antes)

    def test_criacao_direta_bulk_e_update_bloqueados(self):
        for objeto in (self.resgate, self.alocacao):
            modelo = type(objeto)
            valores = modelo.objects.values().get(pk=objeto.pk)
            valores.pop('id')
            for escrever in (lambda: modelo(**valores).save(), lambda: modelo.objects.create(**valores),
                             lambda: modelo.objects.bulk_create([modelo(**valores)]),
                             lambda: modelo.objects.filter(pk=objeto.pk).update(**valores),
                             lambda: modelo.objects.bulk_update([objeto], list(valores))):
                with self.assertRaises(ValidationError):
                    escrever()

    def test_delete_instance_queryset_e_relacoes_protect(self):
        for objeto in (self.resgate, self.alocacao, self.alocacao.lote, self.loja, self.cliente, self.credencial):
            for excluir in (objeto.delete, lambda: type(objeto).objects.filter(pk=objeto.pk).delete()):
                # pre_delete roda em atomic(savepoint=False); isolar a falha
                # esperada para permitir as próximas consultas do TestCase.
                with self.assertRaises(ProtectedError):
                    with transaction.atomic():
                        excluir()
        self.assert_invariantes()

    def test_validacao_model_tipos_nao_finitos_fks_e_snapshots(self):
        valores = Resgate.objects.values().get(pk=self.resgate.pk)
        valores.pop('id')
        valores['identificador_externo'] = 'NOVO'
        invalidos = dict(loja_id=[999999], cliente_id=[999999, self.cliente_externo.pk],
            credencial_origem_id=[999999], pontos_resgatados=[1.0, Decimal('1.5'), Decimal('NaN'), Decimal('sNaN'), Decimal(10**20)],
            valor_desconto=[Decimal('Infinity'), Decimal('9.99')],
            valor_monetario_por_ponto_aplicado=[Decimal('.005'), Decimal('sNaN')],
            resgate_minimo_pontos_aplicado=[True, 0, 200], incremento_resgate_pontos_aplicado=[0, '50'],
            resgatado_em=[None, self.instante.replace(tzinfo=None)])
        for campo, entradas in invalidos.items():
            for entrada in entradas:
                with self.subTest(campo=campo, entrada=entrada), self.assertRaises(ValidationError):
                    Resgate(**dict(valores, **{campo: entrada})).full_clean()
        restrita, _ = self.emitir('LOJAS', [self.segunda])
        with self.assertRaises(ValidationError):
            Resgate(**dict(valores, credencial_origem_id=restrita.pk)).clean()

    def test_alocacao_valida_coerencia_expiracao_soma_e_capacidade(self):
        outro = self.lote(cliente_cpf=self.outro_usuario.cpf)
        expirado = self.lote(ocorrida_em=self.instante.replace(year=2025))
        pequeno = self.lote('1.00')
        for lote in (outro, expirado, pequeno):
            with self.assertRaises(ValidationError):
                AlocacaoResgate(resgate=self.resgate, lote=lote, pontos_consumidos=Decimal('2')).clean()
        for valor in (Decimal('0'), Decimal('-1'), Decimal('NaN'), Decimal('sNaN'), Decimal('Infinity'),
                      Decimal('.00001'), Decimal(10**20), 1.0, Decimal('201')):
            with self.assertRaises(ValidationError):
                AlocacaoResgate(resgate=self.resgate, lote=self.alocacao.lote, pontos_consumidos=valor).clean()
        # O Resgate já está completamente alocado, mesmo com saldo no Lote.
        with self.assertRaises(ValidationError):
            AlocacaoResgate(resgate=self.resgate, lote=self.alocacao.lote, pontos_consumidos=Decimal('1')).clean()
        for campo in ('resgate_id', 'lote_id'):
            valores = dict(resgate_id=self.resgate.pk, lote_id=self.alocacao.lote_id, pontos_consumidos=Decimal('1'))
            valores[campo] = 999999
            with self.assertRaises(ValidationError):
                AlocacaoResgate(**valores).full_clean()

    def test_constraints_sql_unique_e_positividade_defendem_persistencia(self):
        # _base_manager é bypass deliberado e interno, apenas para testar o SQL.
        for objeto, campos in ((self.resgate, ['pontos_resgatados', 'resgate_minimo_pontos_aplicado',
                                'incremento_resgate_pontos_aplicado', 'valor_monetario_por_ponto_aplicado', 'valor_desconto']),
                               (self.alocacao, ['pontos_consumidos'])):
            modelo = type(objeto)
            for campo in campos:
                with self.assertRaises(IntegrityError), transaction.atomic():
                    modelo._base_manager.filter(pk=objeto.pk).update(**{campo: 0})
            valores = modelo.objects.values().get(pk=objeto.pk)
            valores.pop('id')
            with self.assertRaises(IntegrityError), transaction.atomic():
                modelo._base_manager.bulk_create([modelo(**valores)])

    def test_integrity_error_de_constraint_real_diferente_nao_vira_retry(self):
        def violar_check(resgate, *args, **kwargs):
            resgate.valor_desconto = Decimal('0')
            Resgate._base_manager.bulk_create([resgate])

        with patch.object(Resgate, 'save', violar_check):
            with self.assertRaises(IntegrityError) as erro:
                self.resgatar(identificador_externo='CHECK')
        self.assertEqual(erro.exception.__cause__.diag.constraint_name, 'resgate_desconto_positivo')
        self.assertEqual(Resgate.objects.count(), 1)
        self.assertEqual(AlocacaoResgate.objects.count(), 1)

    def test_constraint_idempotente_real_recuperada_apos_savepoint(self):
        antes = Resgate.objects.values().get(pk=self.resgate.pk)
        alocacoes = list(AlocacaoResgate.objects.values())
        # Simula leitura inicial sem vencedor visível; o INSERT efetivo viola
        # somente a unique idempotente. O GET de recuperação usa o banco real.
        with patch.object(Resgate.objects, 'filter') as consultar:
            consultar.return_value.first.return_value = None
            retry, criado = self.resgatar()
        self.assertFalse(criado)
        self.assertEqual(retry.pk, self.resgate.pk)
        self.assertEqual(Resgate.objects.values().get(), antes)
        self.assertEqual(list(AlocacaoResgate.objects.values()), alocacoes)

    def test_contexto_de_escrita_restrito_ao_objeto(self):
        valores = Resgate.objects.values().get(pk=self.resgate.pk)
        valores.pop('id')
        candidato = Resgate(**dict(valores, identificador_externo='OUTRO'))
        with _permitir_escrita_resgates(self.resgate), self.assertRaises(ValidationError):
            candidato.save()
