"""Integração real do seed; não substituir os motores de concessão/consumo."""
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from decimal import Decimal, Inexact, localcontext
from io import StringIO
from threading import Barrier
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, connection, connections, transaction
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.empresas.models import Empresa, ConfiguracaoFidelidadeEmpresa, OverrideFidelidadeLoja
from apps.usuarios.services import resolver_identidade
from apps.usuarios.validators import validar_cpf
from apps.empresas.validators import validar_cnpj

from . import seed_fatecalcados as seed
from . import resgates
from .calculos import calcular_expiracao
from .models import AlocacaoResgate, AplicacaoEfeitoEventoLote, Compra, LotePontos, Resgate
from .niveis import classificar_cliente
from .test_compras import DadosCompras


DATA = date(2026, 9, 24)
SENHA = 'Somente-testes-F4!01-9286'
HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']


def fotografia():
    return {model._meta.label: list(model.objects.order_by('pk').values())
            for app in ('usuarios', 'empresas', 'clientes', 'fidelidade')
            for model in apps.get_app_config(app).get_models()}


def sem_escritas(execute, sql, params, many, context):
    if sql.lstrip().split()[0].upper() in ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'):
        raise AssertionError('Colisão deve ser recusada antes de qualquer escrita.')
    return execute(sql, params, many, context)


def assinatura_logica():
    """Identifica relações por chaves narrativas, nunca por sequências do banco."""
    compras = tuple(Compra.objects.order_by('identificador_externo').values_list(
        'identificador_externo', 'cliente__usuario__cpf', 'loja__nome', 'loja__cidade',
        'valor', 'ocorrida_em', 'lote_pontos__pontos_base', 'lote_pontos__pontos_concedidos',
        'lote_pontos__expira_em', 'lote_pontos__multiplicador_pontos_aplicado'))
    resgates_db = tuple(Resgate.objects.order_by('identificador_externo').values_list(
        'identificador_externo', 'cliente__usuario__cpf', 'loja__nome', 'loja__cidade',
        'pontos_resgatados', 'valor_desconto', 'resgatado_em', 'resgate_minimo_pontos_aplicado',
        'incremento_resgate_pontos_aplicado', 'valor_monetario_por_ponto_aplicado'))
    alocacoes = tuple(AlocacaoResgate.objects.order_by('resgate__identificador_externo',
        'lote__compra__identificador_externo').values_list('resgate__identificador_externo',
        'lote__compra__identificador_externo', 'pontos_consumidos'))
    campanhas = tuple(AplicacaoEfeitoEventoLote.objects.order_by('lote__compra__identificador_externo').values_list(
        'lote__compra__identificador_externo', 'evento__nome', 'evento__inicio_em', 'evento__fim_em',
        'tipo_aplicado', 'valor_aplicado'))
    return compras, resgates_db, alocacoes, campanhas


class PlanoSeedTests(SimpleTestCase):
    def test_data_obrigatoria_e_parsing_estrito(self):
        with self.assertRaises(CommandError):
            call_command('seed_fatecalcados', stdout=StringIO())
        for texto in ('', '2026-9-24', ' 2026-09-24', '2026-09-24 ', '2026-02-29',
                      '24/09/2026', '2026-09-24T12:00:00-03:00', '0000-01-01'):
            with self.subTest(texto=texto), self.assertRaises(CommandError):
                seed.interpretar_data(texto)
        self.assertEqual(seed.interpretar_data('2026-09-24'), DATA)

    def test_plano_calendario_quotas_campanha_e_identidades(self):
        for data in (DATA, date(2024, 2, 29), date(2025, 1, 1), date(2028, 3, 31), date(2026, 12, 31)):
            with self.subTest(data=data):
                plano = seed.montar_plano(data)
                self.assertEqual(plano.referencia.tzinfo.key, 'America/Sao_Paulo')
                self.assertEqual(plano.referencia.hour, 12)
                self.assertEqual(len(plano.vendas), 300)
                self.assertEqual(sum(v.campanha for v in plano.vendas), 24)
                self.assertTrue(all(v.ocorrida_em < plano.referencia for v in plano.vendas))
                meses = Counter((v.ocorrida_em.year - data.year) * 12 + v.ocorrida_em.month - data.month
                                for v in plano.vendas)
                self.assertEqual(set(meses), set(range(-15, 1)))
                self.assertEqual([sum(n for m, n in meses.items() if a <= m <= b)
                                  for a, b in ((-15, -12), (-11, -8), (-7, -4), (-3, 0))], [60, 80, 80, 80])
                self.assertEqual(Counter(v.cliente for v in plano.vendas), {p.codigo: p.compras for p in seed.populacao()})
                self.assertEqual(Counter(v.loja for v in plano.vendas), dict.fromkeys(range(12), 25))
                self.assertEqual(len({v.identificador for v in plano.vendas}), 300)
                self.assertTrue(all((plano.inicio_campanha <= v.ocorrida_em <= plano.fim_campanha) == v.campanha
                                    for v in plano.vendas))
                proximos = [calcular_expiracao(v.ocorrida_em, 12) for v in plano.vendas if v.cliente == 'B01']
                self.assertTrue(any(plano.referencia < t <= plano.referencia + timedelta(days=14) for t in proximos))
        cpfs = [seed.CPF_ADMIN, *(p.cpf for p in seed.populacao())]
        self.assertEqual(len(set(cpfs)), 37)
        for cpf in cpfs:
            validar_cpf(cpf)
        validar_cnpj(seed.CNPJ)

    def test_datas_sem_capacidade_para_historico_ou_validade(self):
        for data in (date.min, date.max, datetime(2026, 9, 24)):
            with self.assertRaises(CommandError):
                seed.montar_plano(data)

    def test_relogio_restrito_restaurado_e_isolado_em_outro_contexto(self):
        original = resgates.timezone
        now_original = timezone.now
        instante = seed.montar_plano(DATA).referencia
        antes = timezone.now()
        with seed._relogio_resgate(instante):
            self.assertEqual(resgates.timezone.now(), instante)
            self.assertIs(timezone.now, now_original)
            with ThreadPoolExecutor(max_workers=1) as pool:
                outro = pool.submit(lambda: resgates.timezone.now()).result(timeout=10)
            self.assertLessEqual(antes, outro)
            self.assertLessEqual(outro, timezone.now())
            with seed._relogio_resgate(instante - timedelta(days=1)):
                self.assertEqual(resgates.timezone.now(), instante - timedelta(days=1))
            self.assertEqual(resgates.timezone.now(), instante)
        self.assertIs(resgates.timezone, original)
        with self.assertRaisesRegex(RuntimeError, 'simulada'):
            with seed._relogio_resgate(instante):
                raise RuntimeError('Falha simulada')
        self.assertIs(resgates.timezone, original)
        self.assertIs(timezone.now, now_original)


@override_settings(PASSWORD_HASHERS=HASHERS)
class CenarioSeedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.resumo = seed.executar_seed(DATA, senha=SENHA)

    def test_estrutura_politica_e_quantidades_reais(self):
        empresa = Empresa.objects.get(cnpj=seed.CNPJ)
        self.assertEqual(empresa.nome, 'FATECalçados')
        self.assertEqual(empresa.slug, 'fatecalcados')
        self.assertCountEqual(empresa.lojas.values_list('nome', 'cidade'), seed.LOJAS)
        self.assertEqual(empresa.clientes.count(), 36)
        self.assertEqual(get_user_model().objects.count(), 37)
        self.assertEqual(empresa.membros.count(), 1)
        self.assertEqual(empresa.membros.get().papel, 'ADMINISTRADOR')
        self.assertEqual(empresa.credenciais_integracao.get().escopo, 'EMPRESA')
        self.assertEqual(empresa.eventos_fidelidade.count(), 1)
        cfg = ConfiguracaoFidelidadeEmpresa.objects.get(empresa=empresa)
        self.assertEqual({k: getattr(cfg, k) for k in seed.POLITICA}, seed.POLITICA)
        self.assertFalse(OverrideFidelidadeLoja.objects.exists())
        self.assertEqual(list(empresa.niveis_fidelidade.values_list('nome', 'pontos_minimos')),
                         [('Bronze', Decimal('0')), ('Prata', Decimal('1000')), ('Ouro', Decimal('5000'))])
        self.assertEqual((Compra.objects.count(), LotePontos.objects.count(), Resgate.objects.count()), (300, 300, 8))
        self.assertEqual(Counter(p['nivel'] for p in self.resumo['pessoas']), {'Bronze': 14, 'Prata': 15, 'Ouro': 7})
        self.assertEqual(Decimal(self.resumo['saldo_em_t']), Decimal('68659.60'))
        self.assertEqual(Decimal(self.resumo['pontos_em_lotes_expirados']), Decimal('15628.00'))
        self.assertEqual(self.resumo['alocacoes'], 22)

    def test_concessoes_campanhas_e_proveniencia_geradas_pelo_dominio(self):
        evento = Empresa.objects.get(cnpj=seed.CNPJ).eventos_fidelidade.get()
        self.assertEqual(evento.efeitos.get().valor, Decimal('2'))
        self.assertEqual(AplicacaoEfeitoEventoLote.objects.count(), 24)
        for compra in Compra.objects.select_related('lote_pontos'):
            lote = compra.lote_pontos
            campanha = evento.inicio_em <= compra.ocorrida_em <= evento.fim_em
            self.assertEqual(lote.pontos_base, compra.valor)
            self.assertEqual(lote.pontos_concedidos, compra.valor * (2 if campanha else 1))
            self.assertEqual(lote.aplicacoes_eventos.exists(), campanha)
            self.assertEqual(lote.adquiridos_em, compra.ocorrida_em)
            self.assertEqual(lote.expira_em, calcular_expiracao(compra.ocorrida_em, 12))
            self.assertEqual((lote.precisao_pontos_aplicada, lote.modo_arredondamento_aplicado), (2, 'HALF_UP'))
            self.assertEqual(lote.cliente_id, compra.cliente_id)
        self.assertEqual(sum(Compra.objects.values_list('valor', flat=True)), Decimal('82337.80'))
        self.assertEqual(sum(LotePontos.objects.values_list('pontos_concedidos', flat=True)), Decimal('89187.60'))

    def test_resgates_fefo_descontos_e_relogio_restaurado(self):
        t = seed.montar_plano(DATA).referencia
        consumido = Counter()
        for i, resgate in enumerate(Resgate.objects.order_by('resgatado_em')):
            self.assertEqual(resgate.resgatado_em, t - timedelta(minutes=8 - i))
            self.assertEqual(resgate.valor_desconto, resgate.pontos_resgatados * Decimal('.05'))
            esperado = {}
            restante = resgate.pontos_resgatados
            for lote in LotePontos.objects.filter(cliente=resgate.cliente, expira_em__gt=resgate.resgatado_em).order_by(
                    'expira_em', 'adquiridos_em', 'pk'):
                if not restante:
                    break
                self.assertLess(lote.adquiridos_em, resgate.resgatado_em)
                quantidade = min(restante, lote.pontos_concedidos - consumido[lote.pk])
                if quantidade:
                    esperado[lote.pk] = quantidade
                    consumido[lote.pk] += quantidade
                    restante -= quantidade
            self.assertEqual(restante, 0)
            self.assertEqual(dict(resgate.alocacoes.values_list('lote_id', 'pontos_consumidos')), esperado)
        self.assertEqual(sum(Resgate.objects.values_list('valor_desconto', flat=True)), Decimal('245'))
        self.assertEqual(sum(Resgate.objects.values_list('pontos_resgatados', flat=True)), Decimal('4900'))
        self.assertIs(resgates.timezone, timezone)

    def test_personagens_nivel_saldo_expiracao_e_atividade_separados(self):
        dados = {p['codigo']: p for p in self.resumo['pessoas']}
        for codigo, pontos, saldo, nivel in (
            ('A01', '6600', '4000', 'Ouro'), ('M01', '2219.10', '1659.30', 'Prata'),
            ('M02', '1409.10', '1029.30', 'Prata'), ('B01', '419.40', '279.60', 'Bronze'),
            ('U01', '149.90', '149.90', 'Bronze'), ('I01', '5500', '3300', 'Ouro'),
        ):
            self.assertEqual((Decimal(dados[codigo]['pontos']), Decimal(dados[codigo]['saldo']), dados[codigo]['nivel']),
                             (Decimal(pontos), Decimal(saldo), nivel))
        self.assertFalse(dados['I01']['compra_na_janela_180d'])
        self.assertEqual(sum(p['compra_na_janela_180d'] for p in dados.values()), 30)
        t = seed.montar_plano(DATA).referencia
        helena = Cliente.objects.get(usuario__cpf=dados['I01']['cpf'])
        self.assertLess(max(helena.compras.values_list('ocorrida_em', flat=True)), t - timedelta(days=210))
        antes = classificar_cliente(helena)
        with patch('apps.fidelidade.models.timezone.now', return_value=t + timedelta(days=1000)):
            self.assertEqual(classificar_cliente(helena), antes)
        bento = Resgate.objects.get(cliente__usuario__cpf=dados['M02']['cpf'])
        self.assertGreaterEqual(bento.alocacoes.count(), 2)
        ravi = Compra.objects.get(cliente__usuario__cpf=dados['M01']['cpf'], lote_pontos__multiplicador_pontos_aplicado=2)
        self.assertEqual((ravi.valor, ravi.lote_pontos.pontos_concedidos), (Decimal('300'), Decimal('600')))

    def test_reexecucao_recusada_antes_de_escrever(self):
        antes = fotografia()
        with connection.execute_wrapper(sem_escritas), self.assertRaises(CommandError):
            seed.executar_seed(DATA, senha=SENHA)
        self.assertEqual(fotografia(), antes)


@override_settings(PASSWORD_HASHERS=HASHERS)
class SegurancaSeedTests(DadosCompras, TestCase):
    def test_outro_tenant_preservado_e_saida_sem_segredos(self):
        antes = fotografia()
        saida = StringIO()
        with patch.dict('os.environ', {'RETORNA_SEED_SENHA': SENHA}):
            call_command('seed_fatecalcados', data_base='2026-09-24', stdout=saida)
        resumo = json.loads(saida.getvalue())
        self.assertEqual((resumo['compras'], resumo['clientes'], resumo['lojas']), (300, 36, 12))
        self.assertNotIn(SENHA, saida.getvalue())
        depois = fotografia()
        for modelo, registros in antes.items():
            for registro in registros:
                self.assertIn(registro, depois[modelo])

    def test_colisoes_cnpj_slug_nome_e_cpf_antes_da_escrita(self):
        colisoes = (
            lambda: Empresa.objects.create(nome='Outra', slug='outra-reservada', cnpj=seed.CNPJ),
            lambda: Empresa.objects.create(nome='Outra', slug=seed.SLUG, cnpj='73182649000225'),
            lambda: Empresa.objects.create(nome=seed.NOME_EMPRESA, slug='nome-reservado', cnpj='73182649000225'),
            lambda: get_user_model().objects.create_user(seed.CPF_ADMIN, SENHA),
            lambda: get_user_model().objects.create_user(seed.populacao()[-1].cpf, SENHA),
        )
        for criar in colisoes:
            with transaction.atomic():
                criar()
                antes = fotografia()
                with connection.execute_wrapper(sem_escritas), self.assertRaises(CommandError):
                    seed.executar_seed(DATA, senha=SENHA)
                self.assertEqual(fotografia(), antes)
                transaction.set_rollback(True)

    def test_identificador_de_operacao_reservado_em_outro_tenant(self):
        self.registrar(identificador_externo=seed.PREFIXO + 'C001')
        antes = fotografia()
        with connection.execute_wrapper(sem_escritas), self.assertRaises(CommandError):
            seed.executar_seed(DATA, senha=SENHA)
        self.assertEqual(fotografia(), antes)

    def test_identidade_surgida_na_corrida_nao_e_reutilizada(self):
        usuario = get_user_model().objects.create_user(seed.CPF_ADMIN, SENHA)
        antes = fotografia()
        with self.assertRaisesRegex(CommandError, 'reutilização recusada'):
            seed._exigir_identidade_nova(usuario.cpf, lambda: resolver_identidade(
                cpf=usuario.cpf, senha=SENHA, confirmacao=SENHA))
        self.assertEqual(fotografia(), antes)

    def test_falhas_de_compra_resgate_e_validacao_final_revertem_tudo(self):
        original = resgates.timezone
        for alvo, real in (('registrar_compra', seed.registrar_compra),
                           ('resgates.registrar_resgate', resgates.registrar_resgate),
                           ('_resumo_e_validacao', seed._resumo_e_validacao)):
            antes = fotografia()

            def falhar(*args, **kwargs):
                real(*args, **kwargs)
                raise ValidationError('Falha depois de persistir pelo fluxo real')

            with self.subTest(alvo=alvo), patch(f'apps.fidelidade.seed_fatecalcados.{alvo}', side_effect=falhar):
                with self.assertRaises(ValidationError):
                    seed.executar_seed(DATA, senha=SENHA)
            self.assertEqual(fotografia(), antes)
            self.assertIs(resgates.timezone, original)

    def test_senha_ausente_recusada_sem_escrita(self):
        with connection.execute_wrapper(sem_escritas), self.assertRaises(CommandError):
            seed.executar_seed(DATA, senha='')


@override_settings(PASSWORD_HASHERS=HASHERS)
class DeterminismoSeedTests(TestCase):
    def test_dois_estados_limpos_equivalentes_sem_comparar_pks_ou_segredos(self):
        resultados = []
        for precisao in (28, 3):
            with transaction.atomic():
                with localcontext() as contexto:
                    contexto.prec = precisao
                    contexto.traps[Inexact] = True
                    resumo = seed.executar_seed(DATA, senha=SENHA)
                resultados.append((resumo, assinatura_logica()))
                # Volta ao banco vazio por rollback de teste, não por reset do seed.
                transaction.set_rollback(True)
            self.assertFalse(Empresa.objects.exists())
        self.assertEqual(resultados[0], resultados[1])


@override_settings(PASSWORD_HASHERS=HASHERS)
class ConcorrenciaSeedTests(TransactionTestCase):
    def test_duas_execucoes_so_uma_carga_completa(self):
        barreira = Barrier(2)
        prechecar = seed._prechecar

        def sincronizar():
            prechecar()
            if not connection.in_atomic_block:
                barreira.wait(timeout=20)

        def executar():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '90s'")
                    cursor.execute("SET statement_timeout = '120s'")
                try:
                    seed.executar_seed(DATA, senha=SENHA)
                    return 'criado'
                except CommandError:
                    return 'recusado'
            finally:
                connections.close_all()

        with patch.object(seed, '_prechecar', side_effect=sincronizar), ThreadPoolExecutor(max_workers=2) as pool:
            futuros = [pool.submit(executar) for _ in range(2)]
            resultados = [f.result(timeout=180) for f in futuros]
        self.assertCountEqual(resultados, ['criado', 'recusado'])
        self.assertEqual((Empresa.objects.count(), Cliente.objects.count(), Compra.objects.count(),
                          LotePontos.objects.count(), Resgate.objects.count()), (1, 36, 300, 300, 8))
        self.assertIs(resgates.timezone, timezone)
