from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from .consultas import consultar_fidelidade_cliente
from .estornos import estornar_resgate
from .exceptions import SaldoInsuficiente
from .models import AlocacaoResgate, EstornoResgate, LotePontos, Resgate
from .resgates import simular_resgate
from .test_resgates import DadosResgates


class DadosEstornos(DadosResgates):
    def estornar(self, **alteracoes):
        dados = dict(credencial=self.credencial, loja_id=self.loja.pk,
                     resgate_identificador_externo='RESGATE-001', identificador_externo='ESTORNO-001')
        dados.update(alteracoes)
        with patch('apps.fidelidade.estornos.timezone.now', return_value=self.instante):
            return estornar_resgate(**dados)

    def consulta(self):
        with patch('apps.fidelidade.consultas.timezone.now', return_value=self.instante):
            return consultar_fidelidade_cliente(credencial=self.credencial, loja_id=self.loja.pk,
                                                cliente_cpf=self.usuario.cpf)

    def simular(self, pontos=100):
        with patch('apps.fidelidade.resgates.timezone.now', return_value=self.instante):
            return simular_resgate(credencial=self.credencial, loja_id=self.loja.pk,
                                   cliente_cpf=self.usuario.cpf, pontos=pontos)


class EstornoSaldoTests(DadosEstornos, TestCase):
    def test_snapshot_v1_compra_sem_parametro_de_estorno_continua_valido(self):
        from copy import deepcopy
        from .beneficios import reavaliar_snapshot

        lote = self.lote()
        snapshot = deepcopy(lote.beneficios_aplicados)
        self.assertNotIn('devolver_pontos_ao_estornar_resgate', snapshot['politica'])
        self.configurar(devolver_pontos_ao_estornar_resgate=False)
        avaliacao = reavaliar_snapshot(
            snapshot, lote.compra.valor, lote.compra.ocorrida_em, lote.multiplicador_pontos_aplicado,
        )
        self.assertEqual(avaliacao.pontos_concedidos, lote.pontos_concedidos)
        self.assertEqual(snapshot, lote.beneficios_aplicados)
        novo = self.lote()
        self.assertNotIn('devolver_pontos_ao_estornar_resgate', novo.beneficios_aplicados['politica'])

    def test_falha_na_persistencia_desfaz_estorno_sem_liberar_saldo(self):
        self.lote()
        self.resgatar()
        salvar = EstornoResgate.save

        def falhar_apos_insert(estorno, *args, **kwargs):
            salvar(estorno, *args, **kwargs)
            raise RuntimeError('Falha após INSERT')

        with patch.object(EstornoResgate, 'save', falhar_apos_insert), self.assertRaises(RuntimeError):
            self.estornar()
        self.assertFalse(EstornoResgate.objects.exists())
        self.assertEqual(self.consulta()['saldo']['pontos'], '0.0000')
        self.assertTrue(self.estornar()[1])
        self.assertEqual(self.consulta()['saldo']['pontos'], '100.0000')

    def test_matriz_snapshot_expiracao_consulta_simulacao_reuso_e_retry_original(self):
        inicio = self.instante
        for devolve in (True, False):
            for expirado in (True, False):
                with self.subTest(devolve=devolve, expirado=expirado), transaction.atomic():
                    self.instante = inicio
                    self.configurar(devolver_pontos_ao_estornar_resgate=devolve)
                    lote = self.lote()
                    chave = f'RESGATE-{devolve}-{expirado}'
                    resgate, _ = self.resgatar(identificador_externo=chave)
                    originais = Resgate.objects.values().get(pk=resgate.pk)
                    alocacao = AlocacaoResgate.objects.values().get(resgate=resgate)
                    lotes = list(LotePontos.objects.values())
                    if expirado:
                        self.instante = lote.expira_em  # limite inclusivo da expiração
                    estorno, _ = self.estornar(resgate_identificador_externo=chave, identificador_externo=chave)
                    self.assertIs(estorno.devolve_pontos_aplicado, devolve)
                    esperado = '100.0000' if devolve and not expirado else '0.0000'
                    self.assertEqual(self.consulta()['saldo']['pontos'], esperado)
                    self.assertEqual(list(LotePontos.objects.values()), lotes)
                    self.assertEqual(Resgate.objects.values().get(pk=resgate.pk), originais)
                    self.assertEqual(AlocacaoResgate.objects.values().get(resgate=resgate), alocacao)
                    with patch('apps.fidelidade.resgates.resolver_configuracao', side_effect=AssertionError('Retry')):
                        retry, criado = self.resgatar(identificador_externo=chave)
                    self.assertFalse(criado)
                    self.assertEqual(retry.pk, resgate.pk)
                    if devolve and not expirado:
                        self.assertEqual(self.simular()['saldo'], {'atual': esperado, 'projetado': '0.0000'})
                        novo, _ = self.resgatar(identificador_externo=f'NOVO-{chave}')
                        self.assertEqual(novo.alocacoes.get().lote_id, lote.pk)
                    else:
                        with self.assertRaises(SaldoInsuficiente):
                            self.simular()
                        with self.assertRaises(SaldoInsuficiente):
                            self.resgatar(identificador_externo=f'NOVO-{chave}')
                    self.assert_invariantes()
                    transaction.set_rollback(True)

    def test_multiplos_lotes_so_parcela_valida_volta_sem_novo_lote(self):
        self.configurar(resgate_minimo_pontos=1, incremento_resgate_pontos=1)
        antigo = self.lote('20.00', ocorrida_em=self.instante - timedelta(days=30))
        valido = self.lote('80.00')
        self.resgatar()
        self.instante = antigo.expira_em
        self.estornar()
        self.assertEqual(self.consulta()['saldo']['pontos'], '80.0000')
        self.assertEqual(self.simular(80)['saldo']['atual'], '80.0000')
        novo, _ = self.resgatar(identificador_externo='REUSO', pontos=80)
        self.assertEqual(novo.alocacoes.get().lote_id, valido.pk)
        self.assertEqual(LotePontos.objects.count(), 2)
        self.assertEqual(self.consulta()['saldo']['pontos'], '0.0000')
        self.assert_invariantes()

    def test_snapshot_nao_muda_saldo_quando_parametro_muda(self):
        self.lote()
        self.resgatar()
        self.estornar()
        self.configurar(devolver_pontos_ao_estornar_resgate=False)
        self.assertEqual(self.consulta()['saldo']['pontos'], '100.0000')
        self.resgatar(identificador_externo='SEGUNDO')
        self.estornar(resgate_identificador_externo='SEGUNDO', identificador_externo='SEGUNDO')
        self.configurar(devolver_pontos_ao_estornar_resgate=True)
        self.assertEqual(self.consulta()['saldo']['pontos'], '0.0000')

    def test_instante_unico_e_ordem_locks_retry_sem_cliente_ou_configuracao(self):
        self.lote()
        self.resgatar()
        consultas = []
        def observar(execute, sql, params, many, context):
            consultas.append(sql)
            return execute(sql, params, many, context)
        with connection.execute_wrapper(observar), \
                patch('apps.fidelidade.estornos.timezone.now', return_value=self.instante) as agora:
            estorno, _ = estornar_resgate(credencial=self.credencial, loja_id=self.loja.pk,
                resgate_identificador_externo='RESGATE-001', identificador_externo='ESTORNO-001')
        agora.assert_called_once_with()
        self.assertEqual(estorno.estornado_em, self.instante)
        locks = [s for s in consultas if 'pg_advisory' in s or 'FOR ' in s]
        self.assertEqual(len(locks), 2)
        self.assertIn('pg_advisory_xact_lock', locks[0])
        self.assertIn('clientes_cliente', locks[1])
        self.assertIn('FOR NO KEY UPDATE', locks[1])
        consultas.clear()
        with connection.execute_wrapper(observar), \
                patch('apps.fidelidade.estornos.resolver_configuracao', side_effect=AssertionError('Retry')):
            self.estornar()
        self.assertFalse(any('FOR ' in s for s in consultas))


class EstornoHistoricoTests(DadosEstornos, TestCase):
    def setUp(self):
        super().setUp()
        self.lote('200.00')
        self.resgate, _ = self.resgatar()
        self.estorno, _ = self.estornar()

    def test_protecao_save_update_bulk_delete_e_criacao(self):
        antes = EstornoResgate.objects.values().get()
        for campo, valor in (('devolve_pontos_aplicado', False), ('identificador_externo', 'OUTRO'),
                             ('estornado_em', self.instante + timedelta(days=1)), ('loja_id', self.segunda.pk),
                             ('cliente_id', self.outro_cliente.pk)):
            candidato = EstornoResgate.objects.get()
            setattr(candidato, campo, valor)
            with self.assertRaises(ValidationError), transaction.atomic():
                candidato.save()
        for executar in (
            lambda: EstornoResgate.objects.update(devolve_pontos_aplicado=False),
            lambda: EstornoResgate.objects.bulk_update([self.estorno], ['devolve_pontos_aplicado']),
            lambda: EstornoResgate.objects.bulk_create([EstornoResgate()]),
            lambda: EstornoResgate.objects.create(),
            lambda: EstornoResgate().save(),
        ):
            with self.assertRaises(ValidationError), transaction.atomic():
                executar()
        for executar in (self.estorno.delete, EstornoResgate.objects.all().delete, self.resgate.delete,
                         self.credencial.delete, self.estorno.cliente.delete, self.loja.delete):
            with self.assertRaises(ProtectedError), transaction.atomic():
                executar()
        self.assertEqual(EstornoResgate.objects.values().get(), antes)

    def test_relacoes_originais_e_credencial_sao_validadas(self):
        for valores in ({'loja_id': self.segunda.pk}, {'cliente_id': self.outro_cliente.pk}):
            dados = dict(resgate=self.resgate, loja=self.loja, cliente=self.resgate.cliente,
                credencial_origem=self.credencial, identificador_externo='NOVO',
                devolve_pontos_aplicado=True, estornado_em=self.instante)
            for nome in valores:
                dados.pop(nome.removesuffix('_id'), None)
            with self.assertRaises(ValidationError):
                EstornoResgate(**dict(dados, **valores)).clean()
        credencial, _ = self.emitir('LOJAS', [self.segunda])
        with self.assertRaises(ValidationError):
            EstornoResgate(resgate=self.resgate, loja=self.loja, cliente=self.resgate.cliente,
                credencial_origem=credencial, identificador_externo='NOVA',
                devolve_pontos_aplicado=True, estornado_em=self.instante).clean()

    def test_constraints_sql_um_estorno_e_chave_unica(self):
        outro, _ = self.resgatar(identificador_externo='OUTRO')
        dados = EstornoResgate.objects.values().get()
        dados.pop('id')
        # Manager base deliberadamente contorna validação Python para exercitar SQL.
        for mudancas in ({'identificador_externo': 'NOVA'}, {'resgate_id': outro.pk}):
            with self.assertRaises(IntegrityError), transaction.atomic():
                EstornoResgate._base_manager.bulk_create([EstornoResgate(**dict(dados, **mudancas))])
