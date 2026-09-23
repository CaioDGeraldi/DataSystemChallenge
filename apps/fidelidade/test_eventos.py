from datetime import timedelta
from decimal import Decimal, Inexact, localcontext
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import SimpleTestCase, TestCase

from apps.empresas.models import ConfiguracaoFidelidadeEmpresa, Loja

from .calculos import calcular_pontos
from .eventos import cancelar_evento, criar_evento, registrar_aplicacao_evento, resolver_efeito_evento
from .exceptions import IdempotenciaConflitante
from .models import AplicacaoEfeitoEventoLote, Compra, EfeitoEvento, EventoFidelidade, EventoLoja, LotePontos
from .test_compras import DadosCompras


class DadosEventos(DadosCompras):
    def evento(self, **alteracoes):
        dados = dict(nome='Campanha', descricao='Concessão temporária', inicio_em=self.instante - timedelta(days=1),
                     fim_em=self.instante + timedelta(days=1), escopo='EMPRESA',
                     efeitos=[{'tipo': 'MULTIPLICADOR_PONTOS', 'valor': Decimal('2.0000')}])
        dados.update(alteracoes)
        request = dados.pop('request', self.request())
        return criar_evento(request, **dados)


class CalculoEventoTests(SimpleTestCase):
    def test_multiplicador_antes_de_uma_unica_politica_preserva_base(self):
        for multiplicador, esperado in [('2.0000', '124.7500'), ('1.0025', '62.5300'),
                                      ('0.5000', '31.1900'), ('1.0000', '62.3800'), ('0.0001', '0.0100')]:
            with self.subTest(multiplicador=multiplicador):
                base, pontos = calcular_pontos(Decimal('49.90'), Decimal('1.25'), 2, 'HALF_UP', Decimal(multiplicador))
                self.assertEqual(str(base), '62.3750')
                self.assertEqual(str(pontos), esperado)
        # Arredondar 62.3750 antes de multiplicar por 2 produziria 124.7600, incorreto.
        for modo, esperado in [('DOWN', '62.5300'), ('UP', '62.5400')]:
            self.assertEqual(str(calcular_pontos(Decimal('49.90'), Decimal('1.25'), 2, modo, Decimal('1.0025'))[1]), esperado)

    def test_extremos_contexto_independente_e_overflow_controlado(self):
        with localcontext() as contexto:
            contexto.prec = 3
            contexto.traps[Inexact] = True
            base, pontos = calcular_pontos(Decimal('9999999999.99'), Decimal('9999999999.99'),
                                          4, 'HALF_UP', Decimal('0.0001'))
            self.assertEqual(str(base), '99999999999800000000.0001')
            self.assertEqual(str(pontos), '9999999999980000.0000')
            self.assertEqual(contexto.prec, 3)
        with self.assertRaises(ValidationError):
            calcular_pontos(Decimal('9999999999.99'), Decimal('9999999999.99'), 4, 'UP', Decimal('99999999.9999'))

    def test_multiplicadores_invalidos_rejeitados_sem_conversao(self):
        for valor in (0, 2.0, True, '2.0000', None, Decimal('0'), Decimal('-1'), Decimal('NaN'),
                      Decimal('Infinity'), Decimal('0.00001'), Decimal('100000000.0000')):
            with self.subTest(valor=valor), self.assertRaises(ValidationError):
                calcular_pontos(Decimal('1.00'), Decimal('1.00'), 2, 'HALF_UP', valor)


class EventoDominioTests(DadosEventos, TestCase):
    def test_empresa_inclui_lojas_atuais_futuras_sem_atravessar_tenant(self):
        evento = self.evento()
        nova = Loja.objects.create(empresa=self.empresa, nome='Nova', cidade='Araras')
        for loja in (self.loja, self.segunda, nova):
            self.assertEqual(resolver_efeito_evento(loja, self.instante).evento_id, evento.pk)
        self.assertIsNone(resolver_efeito_evento(self.externa, self.instante))
        self.assertFalse(evento.lojas_selecionadas.exists())

    def test_lojas_escopo_temporal_inclusivo_e_envio_tardio(self):
        evento = self.evento(escopo='LOJAS', lojas=[self.loja])
        for data in (evento.inicio_em, self.instante, evento.fim_em):
            with patch('apps.fidelidade.models.timezone.now', return_value=evento.fim_em + timedelta(days=2)):
                self.assertEqual(evento.estado, 'ENCERRADO')
                self.assertEqual(resolver_efeito_evento(self.loja, data).evento_id, evento.pk)
                compra, _ = self.registrar(identificador_externo=data.isoformat(), ocorrida_em=data)
                self.assertEqual(compra.lote_pontos.pontos_concedidos, Decimal('399.8000'))
        for data in (evento.inicio_em - timedelta(microseconds=1), evento.fim_em + timedelta(microseconds=1)):
            self.assertIsNone(resolver_efeito_evento(self.loja, data))
        self.assertIsNone(resolver_efeito_evento(self.segunda, self.instante))

    def test_estados_derivados(self):
        evento = self.evento()
        for data, estado in ((evento.inicio_em - timedelta(seconds=1), 'AGENDADO'),
                             (evento.inicio_em, 'VIGENTE'), (evento.fim_em, 'VIGENTE'),
                             (evento.fim_em + timedelta(seconds=1), 'ENCERRADO')):
            with patch('apps.fidelidade.models.timezone.now', return_value=data):
                self.assertEqual(evento.estado, estado)
        evento = cancelar_evento(self.request(), evento.pk)
        self.assertEqual(evento.estado, 'CANCELADO')

    def test_escopo_periodo_efeitos_invalidos_rollback_da_definicao(self):
        for dados in (
            {'escopo': 'LOJAS', 'lojas': []}, {'escopo': 'LOJAS', 'lojas': [self.externa]},
            {'escopo': 'EMPRESA', 'lojas': [self.loja]}, {'escopo': 'INVALID'},
            {'inicio_em': self.instante, 'fim_em': self.instante},
            {'inicio_em': self.instante.replace(tzinfo=None)}, {'efeitos': []},
            {'efeitos': [{'tipo': 'BONUS_PONTOS_PERCENTUAL', 'valor': Decimal('2')}]},
            {'efeitos': [{'tipo': 'MULTIPLICADOR_PONTOS', 'valor': Decimal('2')}] * 2},
        ):
            with self.subTest(dados=dados), self.assertRaises(ValidationError):
                self.evento(**dados)
            self.assertFalse(EventoFidelidade.objects.exists())
            self.assertFalse(EfeitoEvento.objects.exists())
        for valor in (Decimal('0'), Decimal('-1'), 2.0, Decimal('0.00001')):
            with self.assertRaises(ValidationError):
                self.evento(efeitos=[{'tipo': 'MULTIPLICADOR_PONTOS', 'valor': valor}])
            self.assertFalse(EventoFidelidade.objects.exists())

    def test_conflitos_todos_escopos_e_fronteiras(self):
        for primeiro, segundo in (
            ({}, {}), ({}, {'escopo': 'LOJAS', 'lojas': [self.loja]}),
            ({'escopo': 'LOJAS', 'lojas': [self.loja]}, {}),
            ({'escopo': 'LOJAS', 'lojas': [self.loja, self.segunda]}, {'escopo': 'LOJAS', 'lojas': [self.segunda]}),
        ):
            with self.subTest(primeiro=primeiro, segundo=segundo):
                evento = self.evento(**primeiro)
                for inicio in (evento.inicio_em, evento.fim_em):
                    with self.assertRaises(ValidationError):
                        self.evento(**dict(segundo, inicio_em=inicio, fim_em=evento.fim_em + timedelta(days=1)))
                cancelar_evento(self.request(), evento.pk)

    def test_sem_intersecao_sem_sobreposicao_e_outra_empresa_permitidos(self):
        evento = self.evento(escopo='LOJAS', lojas=[self.loja])
        self.evento(escopo='LOJAS', lojas=[self.segunda])
        self.evento(inicio_em=evento.fim_em + timedelta(microseconds=1), fim_em=evento.fim_em + timedelta(days=1))
        self.evento(request=self.request(self.outro_membro))
        self.assertEqual(EventoFidelidade.objects.count(), 4)

    def test_cancelar_e_recriar_preserva_instante_original_sem_reativacao(self):
        evento = self.evento()
        cancelado = cancelar_evento(self.request(), evento.pk)
        instante = cancelado.cancelado_em
        novamente = cancelar_evento(self.request(), evento.pk)
        self.assertEqual(novamente.cancelado_em, instante)
        for data in (None, instante + timedelta(seconds=1)):
            novamente.cancelado_em = data
            with self.assertRaises(ValidationError):
                novamente.save(update_fields=['cancelado_em'])
        novo = self.evento()
        self.assertNotEqual(novo.pk, evento.pk)
        self.assertEqual(resolver_efeito_evento(self.loja, self.instante).evento_id, novo.pk)
        with self.assertRaises(ValidationError):
            evento.save()  # Instância antiga não pode apagar cancelamento concorrente.

    def test_definicao_evento_imutavel_inclusive_pk_reconstruida_e_update_fields(self):
        evento = self.evento()
        antes = EventoFidelidade.objects.values().get(pk=evento.pk)
        for campo, valor in {'empresa_id': self.outra.pk, 'nome': 'Outro', 'descricao': 'Outra',
                             'inicio_em': evento.inicio_em - timedelta(days=1), 'fim_em': evento.fim_em + timedelta(days=1),
                             'escopo': 'LOJAS', 'criado_por_id': self.outro_membro.pk,
                             'criado_em': evento.criado_em + timedelta(seconds=1)}.items():
            for parcial in (False, True):
                with self.subTest(campo=campo, parcial=parcial):
                    reconstruido = EventoFidelidade(**dict(antes, **{campo: valor}))
                    with self.assertRaises(ValidationError):
                        reconstruido.save(**({'update_fields': ['nome']} if parcial else {}))
                    self.assertEqual(EventoFidelidade.objects.values().get(pk=evento.pk), antes)
        evento.save()
        evento.cancelado_em = self.instante
        with self.assertRaises(ValidationError):
            evento.save()  # Cancelamento exige o caso de uso explícito.

    def test_conjunto_lojas_e_efeitos_congelados_e_protegidos(self):
        evento = self.evento(escopo='LOJAS', lojas=[self.loja, self.segunda])
        efeito = evento.efeitos.get()
        acesso = evento.lojas_selecionadas.get(loja=self.loja)
        self.assertEqual(evento.lojas_selecionadas.count(), 2)
        with self.assertRaises(ValidationError):
            EventoLoja.objects.create(evento=evento, loja=self.externa)
        nova = Loja.objects.create(empresa=self.empresa, nome='Nova', cidade='Araras')
        with self.assertRaises(ValidationError):
            EventoLoja.objects.create(evento=evento, loja=nova)
        for objeto, campo, valor in ((acesso, 'loja', nova), (acesso, 'loja', self.externa),
                                     (efeito, 'valor', Decimal('3')), (efeito, 'tipo', 'BONUS_PONTOS_PERCENTUAL')):
            setattr(objeto, campo, valor)
            with self.assertRaises(ValidationError):
                objeto.save()
            objeto.refresh_from_db()
        for objeto in (evento, efeito, acesso):
            # pre_delete executa dentro de atomic(savepoint=False) no Django.
            with self.assertRaises(ProtectedError), transaction.atomic():
                objeto.delete()
            with self.assertRaises(ProtectedError), transaction.atomic():
                type(objeto).objects.filter(pk=objeto.pk).delete()
        with self.assertRaises(ValidationError):
            EfeitoEvento.objects.create(evento=evento, tipo=efeito.tipo, valor=efeito.valor)

    def test_constraints_sql_efeito_unico_periodo_e_valor(self):
        evento = self.evento()
        efeito = evento.efeitos.get()
        for modelo, pk, dados in ((EventoFidelidade, evento.pk, {'fim_em': evento.inicio_em}),
                                  (EventoFidelidade, evento.pk, {'escopo': 'INVALID'}),
                                  (EfeitoEvento, efeito.pk, {'valor': 0}),
                                  (EfeitoEvento, efeito.pk, {'tipo': 'INVALID'})):
            with self.assertRaises(IntegrityError), transaction.atomic():
                modelo.objects.filter(pk=pk).update(**dados)
        with self.assertRaises(IntegrityError), transaction.atomic():
            EfeitoEvento.objects.bulk_create([EfeitoEvento(evento=evento, tipo=efeito.tipo, valor=efeito.valor)])

    def test_autorizacao_service_revalida_tenant_gestor_e_inativo(self):
        externo = self.evento(request=self.request(self.outro_membro))
        with self.assertRaises(PermissionDenied):
            cancelar_evento(self.request(), externo.pk)
        for papel, ativo in (('GESTOR', True), ('ADMINISTRADOR', False)):
            self.membro.papel, self.membro.ativo = papel, ativo
            self.membro.save()
            with self.assertRaises(PermissionDenied):
                self.evento()
            with self.assertRaises(PermissionDenied):
                cancelar_evento(self.request(), externo.pk)


class AplicacaoEventoTests(DadosEventos, TestCase):
    def test_concessao_snapshot_e_sem_evento_ou_evento_neutro(self):
        sem, _ = self.registrar()
        self.assertEqual(sem.lote_pontos.multiplicador_pontos_aplicado, Decimal('1.0000'))
        self.assertFalse(sem.lote_pontos.aplicacoes_eventos.exists())
        evento = self.evento(efeitos=[{'tipo': 'MULTIPLICADOR_PONTOS', 'valor': Decimal('1.0000')}])
        com, _ = self.registrar(identificador_externo='COM')
        aplicacao = com.lote_pontos.aplicacoes_eventos.get()
        self.assertEqual(com.lote_pontos.pontos_concedidos, sem.lote_pontos.pontos_concedidos)
        self.assertEqual(aplicacao.evento_id, evento.pk)
        self.assertEqual(aplicacao.efeito_id, evento.efeitos.get().pk)
        self.assertEqual(aplicacao.valor_aplicado, Decimal('1.0000'))
        self.assertEqual(aplicacao.tipo_aplicado, 'MULTIPLICADOR_PONTOS')

    def test_cancelamento_e_mudancas_nao_invalidam_historico_retry_nao_resolve(self):
        evento = self.evento()
        compra, _ = self.registrar()
        lote = compra.lote_pontos
        aplicacao = lote.aplicacoes_eventos.get()
        antes = AplicacaoEfeitoEventoLote.objects.values().get()
        cancelar_evento(self.request(), evento.pk)
        ConfiguracaoFidelidadeEmpresa.objects.create(empresa=self.empresa, pontos_por_real=Decimal('2.00'))
        lote.full_clean()
        aplicacao.full_clean()
        aplicacao.save()
        outra, _ = self.emitir()
        with patch('apps.fidelidade.services.resolver_efeito_evento', side_effect=AssertionError('Retry não resolve Evento')):
            retry, criada = self.registrar(credencial=outra)
            self.assertFalse(criada)
            self.assertEqual(retry.lote_pontos.pk, lote.pk)
            with self.assertRaises(IdempotenciaConflitante):
                self.registrar(valor=Decimal('200.00'))
        self.assertEqual(AplicacaoEfeitoEventoLote.objects.values().get(), antes)
        nova, _ = self.registrar(identificador_externo='NOVA')
        self.assertFalse(nova.lote_pontos.aplicacoes_eventos.exists())
        self.assertEqual(nova.lote_pontos.multiplicador_pontos_aplicado, Decimal('1.0000'))

    def test_lote_valida_multiplicador_e_snapshot_imutavel(self):
        self.evento()
        compra, _ = self.registrar()
        lote = compra.lote_pontos
        self.assertEqual(lote.pontos_base, Decimal('199.9000'))
        self.assertEqual(lote.pontos_concedidos, Decimal('399.8000'))
        valores = LotePontos.objects.values().get()
        for valor in (Decimal('1.0000'), Decimal('0'), Decimal('-1'), 2.0):
            candidato = LotePontos(**dict(valores, multiplicador_pontos_aplicado=valor))
            with self.assertRaises(ValidationError):
                candidato.save(update_fields=['pontos_base'])
        valores.pop('id')
        candidato = LotePontos(**dict(valores, pontos_concedidos=Decimal('199.9000')))
        with self.assertRaises(ValidationError):
            candidato.clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            LotePontos.objects.filter(pk=lote.pk).update(multiplicador_pontos_aplicado=0)

    def test_aplicacao_coerente_e_imutavel_todos_campos(self):
        evento = self.evento(escopo='LOJAS', lojas=[self.loja])
        compra, _ = self.registrar()
        antes = AplicacaoEfeitoEventoLote.objects.values().get()
        externo = self.evento(request=self.request(self.outro_membro))
        outra_compra, _ = self.registrar(identificador_externo='OUTRA', loja_id=self.segunda.pk)
        alteracoes = {'lote_id': outra_compra.lote_pontos.pk, 'evento_id': externo.pk,
                      'efeito_id': externo.efeitos.get().pk, 'tipo_aplicado': 'INVALID',
                      'valor_aplicado': Decimal('1.0000'), 'criado_em': antes['criado_em'] + timedelta(seconds=1)}
        for campo, valor in alteracoes.items():
            for metodo in ('clean', 'save', 'parcial'):
                candidato = AplicacaoEfeitoEventoLote(**dict(antes, **{campo: valor}))
                with self.subTest(campo=campo, metodo=metodo), self.assertRaises(ValidationError):
                    if metodo == 'parcial':
                        candidato.save(update_fields=['valor_aplicado'])
                    else:
                        getattr(candidato, metodo)()
        valores = dict(antes)
        valores.pop('id')
        for mudancas in ({'valor_aplicado': Decimal('1')}, {'evento_id': externo.pk},
                         {'efeito_id': externo.efeitos.get().pk}, {'lote_id': outra_compra.lote_pontos.pk}):
            with self.assertRaises(ValidationError):
                AplicacaoEfeitoEventoLote(**dict(valores, **mudancas)).clean()
        # Mesmo valor do Efeito, mas snapshot numérico do Lote incompatível.
        LotePontos.objects.filter(pk=compra.lote_pontos.pk).update(multiplicador_pontos_aplicado=Decimal('1'))
        with self.assertRaises(ValidationError):
            AplicacaoEfeitoEventoLote(**valores).clean()
        self.assertEqual(AplicacaoEfeitoEventoLote.objects.values().get(), antes)
        for objeto in (compra.lote_pontos, evento, evento.efeitos.get(), AplicacaoEfeitoEventoLote.objects.get()):
            with self.assertRaises(ProtectedError), transaction.atomic():
                objeto.delete()

    def test_falhas_de_resolucao_calculo_e_snapshot_revertem_toda_operacao(self):
        self.evento()
        original = AplicacaoEfeitoEventoLote.save

        def inserir_e_falhar(objeto, *args, **kwargs):
            original(objeto, *args, **kwargs)
            raise ValidationError('Falha simulada após INSERT.')

        for alvo in ('resolver_efeito_evento', 'calcular_pontos', 'registrar_aplicacao_evento'):
            with patch('apps.fidelidade.services.' + alvo, side_effect=ValidationError('Falha simulada')):
                with self.assertRaises(ValidationError):
                    self.registrar()
            self.assertFalse(Compra.objects.exists())
            self.assertFalse(LotePontos.objects.exists())
            self.assertFalse(AplicacaoEfeitoEventoLote.objects.exists())
        with patch.object(AplicacaoEfeitoEventoLote, 'save', autospec=True, side_effect=inserir_e_falhar):
            with self.assertRaises(ValidationError):
                self.registrar()
        self.assertFalse(Compra.objects.exists())
        self.assertFalse(LotePontos.objects.exists())
        self.assertFalse(AplicacaoEfeitoEventoLote.objects.exists())

    def test_overflow_do_resultado_rollback_e_legado_sem_resolucao(self):
        self.evento()
        ConfiguracaoFidelidadeEmpresa.objects.create(empresa=self.empresa, pontos_por_real=Decimal('9999999999.99'))
        with self.assertRaises(ValidationError):
            self.registrar(valor=Decimal('9999999999.99'))
        self.assertFalse(Compra.objects.exists())
        self.assertFalse(LotePontos.objects.exists())
        self.assertFalse(AplicacaoEfeitoEventoLote.objects.exists())
        legada = self.model()
        legada.save()
        with patch('apps.fidelidade.services.resolver_efeito_evento', side_effect=AssertionError('Sem backfill')):
            retry, criada = self.registrar()
        self.assertFalse(criada)
        self.assertEqual(retry.pk, legada.pk)
        self.assertFalse(LotePontos.objects.exists())


    def test_constraints_aplicacao_e_proibicao_de_anexacao_retroativa(self):
        evento = self.evento()
        compra, _ = self.registrar()
        aplicacao = AplicacaoEfeitoEventoLote.objects.get()
        dados = AplicacaoEfeitoEventoLote.objects.values().get()
        dados.pop('id')
        with self.assertRaises(IntegrityError), transaction.atomic():
            AplicacaoEfeitoEventoLote.objects.bulk_create([AplicacaoEfeitoEventoLote(**dados)])
        for mudanca in ({'valor_aplicado': 0}, {'tipo_aplicado': 'INVALID'}):
            with self.assertRaises(IntegrityError), transaction.atomic():
                AplicacaoEfeitoEventoLote.objects.filter(pk=aplicacao.pk).update(**mudanca)
        with self.assertRaises(ValidationError), transaction.atomic():
            registrar_aplicacao_evento(compra.lote_pontos, evento.efeitos.get())

    def test_erro_de_integridade_do_snapshot_nao_vira_retry(self):
        self.evento()
        with patch('apps.fidelidade.services.registrar_aplicacao_evento', side_effect=IntegrityError('Falha simulada')):
            with self.assertRaises(IntegrityError):
                self.registrar()
        self.assertFalse(Compra.objects.exists())
        self.assertFalse(LotePontos.objects.exists())
        self.assertFalse(AplicacaoEfeitoEventoLote.objects.exists())


    def test_taxa_zero_ainda_registra_lote_e_proveniencia(self):
        self.evento()
        ConfiguracaoFidelidadeEmpresa.objects.create(empresa=self.empresa, pontos_por_real=Decimal('0.00'))
        compra, _ = self.registrar()
        lote = compra.lote_pontos
        self.assertEqual(lote.pontos_base, Decimal('0.0000'))
        self.assertEqual(lote.pontos_concedidos, Decimal('0.0000'))
        self.assertEqual(lote.aplicacoes_eventos.count(), 1)
