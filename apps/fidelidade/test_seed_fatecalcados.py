"""Integração real do seed; não substituir os motores de concessão/consumo."""
import json
import os
import stat
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from decimal import Decimal, Inexact, ROUND_HALF_UP, localcontext
from io import StringIO
from threading import Barrier
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, connection, connections, transaction, IntegrityError
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from django.http import HttpRequest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.clientes.models import Cliente
from apps.empresas.models import Empresa, ConfiguracaoFidelidadeEmpresa, OverrideFidelidadeLoja
from apps.usuarios.services import (
    CONTEXTO_SESSAO, ativar_contexto, resolver_identidade, resolver_contextos, validar_contexto_ativo,
)
from apps.empresas.services import (
    resolver_lojas_visiveis, criar_loja_no_contexto, autenticar_credencial,
    resolver_configuracao, salvar_override_loja,
)
from apps.usuarios.validators import validar_cpf
from apps.empresas.validators import validar_cnpj

from . import seed_fatecalcados as seed
from . import resgates, estornos, consultas, simulacoes
from .calculos import calcular_expiracao
from .models import AlocacaoResgate, AplicacaoEfeitoEventoLote, Compra, LotePontos, Resgate, EstornoResgate
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
    snapshots = []
    for lote in LotePontos.objects.order_by('compra__identificador_externo'):
        snapshot = deepcopy(lote.beneficios_aplicados)
        for nivel in snapshot['niveis']:
            nivel.pop('id')
        for campo in ('nivel_anterior', 'nivel_bonus'):
            if snapshot['resultado'][campo]:
                snapshot['resultado'][campo].pop('id')
        snapshots.append(snapshot)
    estornos_db = tuple(EstornoResgate.objects.order_by('identificador_externo').values_list(
        'identificador_externo', 'resgate__identificador_externo', 'estornado_em', 'devolve_pontos_aplicado'))
    overrides = tuple(OverrideFidelidadeLoja.objects.order_by('loja__nome', 'loja__cidade').values_list(
        'loja__nome', 'loja__cidade', 'pontos_por_real'))
    return compras, resgates_db, alocacoes, campanhas, snapshots, estornos_db, overrides


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
                self.assertEqual(len(plano.vendas), 303)
                self.assertEqual(sum(v.campanha for v in plano.vendas), 25)
                self.assertTrue(all(v.ocorrida_em < plano.referencia for v in plano.vendas))
                meses = Counter((v.ocorrida_em.year - data.year) * 12 + v.ocorrida_em.month - data.month
                                for v in plano.vendas)
                self.assertEqual(set(meses), set(range(-15, 1)))
                self.assertEqual([sum(n for m, n in meses.items() if a <= m <= b)
                                  for a, b in ((-15, -12), (-11, -8), (-7, -4), (-3, 0))], [61, 80, 80, 82])
                self.assertEqual(Counter(v.cliente for v in plano.vendas), {p.codigo: p.compras + (p.codigo in ('U01', 'I02', 'I03')) for p in seed.populacao()})
                self.assertEqual(Counter(v.loja for v in plano.vendas), {i: 26 if i < 3 else 25 for i in range(12)})
                self.assertEqual(len({v.identificador for v in plano.vendas}), 303)
                self.assertTrue(all((plano.inicio_campanha <= v.ocorrida_em <= plano.fim_campanha) == v.campanha
                                    for v in plano.vendas))
                proximos = [calcular_expiracao(v.ocorrida_em, 12) for v in plano.vendas if v.cliente == 'B01']
                self.assertTrue(any(plano.referencia < t <= plano.referencia + timedelta(days=14) for t in proximos))
        cpfs = [seed.CPF_ADMIN, seed.CPF_GESTOR, *(p.cpf for p in seed.populacao())]
        self.assertEqual(len(set(cpfs)), 38)
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
        criar = seed.criar_credencial

        def capturar(*args, **kwargs):
            credencial, cls.chave = criar(*args, **kwargs)
            return credencial, cls.chave

        with patch.object(seed, 'criar_credencial', side_effect=capturar):
            cls.resumo = seed.executar_seed(DATA, senha=SENHA)

    def test_estrutura_politica_e_quantidades_reais(self):
        empresa = Empresa.objects.get(cnpj=seed.CNPJ)
        self.assertEqual(empresa.nome, 'FATECalçados')
        self.assertEqual(empresa.slug, 'fatecalcados')
        self.assertCountEqual(empresa.lojas.values_list('nome', 'cidade'), seed.LOJAS)
        self.assertEqual(empresa.clientes.count(), 36)
        self.assertEqual(get_user_model().objects.count(), 38)
        self.assertEqual(empresa.membros.count(), 2)
        self.assertEqual(empresa.membros.get(usuario__cpf=seed.CPF_ADMIN).papel, 'ADMINISTRADOR')
        self.assertEqual(empresa.credenciais_integracao.get().escopo, 'EMPRESA')
        self.assertEqual(empresa.eventos_fidelidade.count(), 1)
        cfg = ConfiguracaoFidelidadeEmpresa.objects.get(empresa=empresa)
        self.assertEqual(cfg.limite_resgate_percentual, Decimal("50.0000"))
        self.assertEqual({k: getattr(cfg, k) for k in seed.POLITICA}, seed.POLITICA)
        self.assertEqual(OverrideFidelidadeLoja.objects.filter(loja__empresa=empresa).count(), 1)
        self.assertEqual(self.resumo['overrides_loja'], 1)
        self.assertEqual(list(empresa.niveis_fidelidade.values_list('nome', 'pontos_minimos')),
                         [('Bronze', Decimal('0')), ('Prata', Decimal('1000')), ('Ouro', Decimal('5000'))])
        self.assertEqual((Compra.objects.count(), LotePontos.objects.count(), Resgate.objects.count()), (303, 303, 8))
        self.assertEqual(Counter(p['nivel'] for p in self.resumo['pessoas']), {'Bronze': 14, 'Prata': 15, 'Ouro': 7})
        self.assertEqual(EstornoResgate.objects.count(), 1)
        self.assertEqual(self.resumo['clientes_ativos'], 32)
        self.assertEqual(cfg.base_calculo_pontos, 'BRUTO')
        self.assertEqual(tuple(empresa.niveis_fidelidade.values_list(
            'nome', 'pontos_minimos', 'bonus_pontos_percentual', 'desconto_percentual')), seed.NIVEIS)
        self.assertEqual(Decimal(self.resumo['saldo_em_t']), Decimal('85523.93'))
        self.assertEqual(Decimal(self.resumo['pontos_concedidos']), Decimal('107961.83'))
        self.assertEqual(Decimal(self.resumo['pontos_em_lotes_expirados']), Decimal('17737.90'))
        self.assertEqual(self.resumo['alocacoes'], 22)
        self.assertEqual(Decimal(self.resumo['valor_compras']), Decimal('83087.70'))
        self.assertEqual(Decimal(self.resumo['valor_final_compras']), Decimal('79543.01'))

    def test_override_exclusivo_e_heranca_dos_demais_parametros(self):
        empresa = Empresa.objects.get(cnpj=seed.CNPJ)
        override = OverrideFidelidadeLoja.objects.get(loja__empresa=empresa)
        self.assertEqual((override.loja.nome, override.loja.cidade, override.pontos_por_real),
                         ('Jardim Aurora', 'Araras', Decimal('2.00')))
        corporativa = resolver_configuracao(empresa)
        self.assertEqual(corporativa.pontos_por_real, Decimal('1.00'))
        for loja in empresa.lojas.all():
            with self.subTest(loja=(loja.nome, loja.cidade)):
                tem_override = (loja.nome, loja.cidade) == ('Jardim Aurora', 'Araras')
                self.assertEqual(OverrideFidelidadeLoja.objects.filter(loja=loja).exists(), tem_override)
                esperado = asdict(corporativa)
                esperado.update(loja_id=loja.pk, pontos_por_real=Decimal('2.00' if tem_override else '1.00'))
                self.assertEqual(asdict(resolver_configuracao(empresa, loja)), esperado)

    def test_compras_equivalentes_usam_taxa_efetiva_por_loja(self):
        empresa = Empresa.objects.get(cnpj=seed.CNPJ)
        credencial = empresa.credenciais_integracao.get()
        antes = assinatura_logica()
        for nome, base, concedidos in (('Centro', '300', '405'), ('Jardim Aurora', '600', '810')):
            with self.subTest(loja=nome), transaction.atomic():
                # Mesma Helena, estado inicial, valor e instante em cada ramo.
                loja = empresa.lojas.get(nome=nome, cidade='Araras')
                compra, criada = seed.registrar_compra(credencial=credencial, loja_id=loja.pk,
                    cliente_cpf=seed.CPF_HELENA, identificador_externo='COMPARACAO-OVERRIDE',
                    valor=Decimal('300.00'), ocorrida_em=seed.montar_plano(DATA).referencia)
                self.assertTrue(criada)
                self.assertEqual(compra.valor, Decimal('300.00'))
                self.assertEqual(compra.lote_pontos.pontos_base, Decimal(base))
                self.assertEqual(compra.lote_pontos.pontos_concedidos, Decimal(concedidos))
                self.assertEqual(Decimal(compra.lote_pontos.beneficios_aplicados['resultado']['valor_final']),
                                 Decimal('240.00'))
                transaction.set_rollback(True)
        self.assertEqual(assinatura_logica(), antes)

    def test_validacao_final_recusa_override_adicional_ou_valor_incorreto(self):
        empresa = Empresa.objects.get(cnpj=seed.CNPJ)
        clientes = {p.codigo: Cliente.objects.get(empresa=empresa, usuario__cpf=p.cpf)
                    for p in seed.populacao()}
        membro = empresa.membros.get(papel='ADMINISTRADOR')
        request = HttpRequest()
        request.user, request.session = membro.usuario, {}
        ativar_contexto(request, 'gestao', membro.pk)
        for nome in ('Centro', 'Jardim Aurora'):
            with self.subTest(loja=nome), transaction.atomic():
                loja = empresa.lojas.get(nome=nome, cidade='Araras')
                salvar_override_loja(request, loja.pk, pontos_por_real=Decimal('3.00'))
                with self.assertRaisesRegex(CommandError, 'Override exclusivo'):
                    seed._resumo_e_validacao(empresa, clientes, seed.montar_plano(DATA), senha=SENHA)
                transaction.set_rollback(True)

    def test_concessoes_campanhas_e_proveniencia_geradas_pelo_dominio(self):
        evento = Empresa.objects.get(cnpj=seed.CNPJ).eventos_fidelidade.get()
        self.assertEqual(evento.efeitos.get().valor, Decimal('2'))
        self.assertEqual(AplicacaoEfeitoEventoLote.objects.count(), 25)
        for compra in Compra.objects.select_related('lote_pontos', 'loja'):
            lote = compra.lote_pontos
            campanha = evento.inicio_em <= compra.ocorrida_em <= evento.fim_em
            taxa = Decimal('2.00') if (compra.loja.nome, compra.loja.cidade) == seed.LOJAS[1] else Decimal('1.00')
            self.assertEqual(lote.pontos_por_real_aplicado, taxa)
            self.assertEqual(lote.pontos_base, compra.valor * taxa)
            resultado = lote.beneficios_aplicados['resultado']
            self.assertEqual(lote.pontos_concedidos, (compra.valor * taxa * (
                Decimal(2 if campanha else 1) + Decimal(resultado['bonus_nivel']) / 100
                + Decimal(resultado['bonus_retorno']) / 100)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))
            self.assertEqual(lote.aplicacoes_eventos.exists(), campanha)
            self.assertEqual(lote.adquiridos_em, compra.ocorrida_em)
            self.assertEqual(lote.expira_em, calcular_expiracao(compra.ocorrida_em, 12))
            self.assertEqual((lote.precisao_pontos_aplicada, lote.modo_arredondamento_aplicado), (2, 'HALF_UP'))
            self.assertEqual(lote.cliente_id, compra.cliente_id)
        self.assertEqual(sum(Compra.objects.values_list('valor', flat=True)), Decimal('83087.70'))
        self.assertEqual(sum(LotePontos.objects.values_list('pontos_concedidos', flat=True)),
                         Decimal(self.resumo['pontos_concedidos']))

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
        for codigo, nivel in (('A01', 'Ouro'), ('M01', 'Prata'), ('M02', 'Prata'),
                              ('B01', 'Bronze'), ('U01', 'Bronze'), ('I01', 'Ouro')):
            self.assertEqual(dados[codigo]['nivel'], nivel)
        self.assertEqual(Decimal(dados['I01']['pontos']), Decimal('6160'))
        self.assertEqual(Decimal(dados['I01']['saldo']), Decimal('3740'))
        self.assertFalse(dados['I01']['compra_na_janela_180d'])
        self.assertEqual(sum(p['compra_na_janela_180d'] for p in dados.values()), 32)
        t = seed.montar_plano(DATA).referencia
        helena = Cliente.objects.get(usuario__cpf=dados['I01']['cpf'])
        self.assertLess(max(helena.compras.values_list('ocorrida_em', flat=True)), t - timedelta(days=210))
        antes = classificar_cliente(helena)
        with patch('apps.fidelidade.models.timezone.now', return_value=t + timedelta(days=1000)):
            self.assertEqual(classificar_cliente(helena), antes)
        bento = Resgate.objects.get(cliente__usuario__cpf=dados['M02']['cpf'])
        self.assertGreaterEqual(bento.alocacoes.count(), 2)
        ravi = Compra.objects.get(cliente__usuario__cpf=dados['M01']['cpf'], lote_pontos__multiplicador_pontos_aplicado=2)
        self.assertEqual((ravi.valor, ravi.lote_pontos.pontos_concedidos), (Decimal('300'), Decimal('630')))

    def test_contas_demo_e_escopo_real_do_gestor(self):
        empresa = Empresa.objects.get(cnpj=seed.CNPJ)
        self.assertEqual((seed.CPF_ADMIN, seed.CPF_GESTOR, seed.CPF_HELENA),
                         ('73182000039', '73182009095', '73182003135'))
        for membro in empresa.membros.select_related('usuario'):
            self.assertTrue(membro.usuario.check_password(SENHA))
            request = HttpRequest()
            request.user, request.session = membro.usuario, {}
            ativar_contexto(request, 'gestao', membro.pk)
            admin = membro.papel == 'ADMINISTRADOR'
            visiveis = resolver_lojas_visiveis(request)
            self.assertCountEqual(visiveis.values_list('nome', 'cidade'), seed.LOJAS if admin else seed.LOJAS[:2])
            self.assertEqual(membro.acessos_lojas.count(), 0 if admin else 2)
            if not admin:
                for nome, cidade in seed.LOJAS[2:]:
                    self.assertFalse(visiveis.filter(nome=nome, cidade=cidade).exists())
                with self.assertRaises(PermissionDenied):
                    criar_loja_no_contexto(request, nome='Não autorizada', cidade='Araras')
                for loja in visiveis:
                    with self.assertRaises(PermissionDenied):
                        salvar_override_loja(request, loja.pk, pontos_por_real=Decimal('3.00'))
            self.assertTrue(self.client.login(cpf=membro.usuario.cpf, password=SENHA))
            sessao = self.client.session
            sessao.update(request.session)
            sessao.save()
            resposta = self.client.get(reverse('empresas:area'))
            self.assertEqual(resposta.status_code, 200)
            self.assertCountEqual(resposta.context['lojas'].values_list('nome', 'cidade'),
                                  seed.LOJAS if admin else seed.LOJAS[:2])
        self.assertEqual(empresa.convites.get().cpf, seed.CPF_GESTOR)
        self.assertIsNotNone(empresa.convites.get().aceito_em)

    def test_administrador_sem_autenticacao_impede_validacao_final(self):
        empresa = Empresa.objects.get(cnpj=seed.CNPJ)
        clientes = {p.codigo: Cliente.objects.get(empresa=empresa, usuario__cpf=p.cpf)
                    for p in seed.populacao()}
        with patch.object(seed, 'authenticate', return_value=None):
            with self.assertRaisesRegex(CommandError, 'não pode autenticar'):
                seed._resumo_e_validacao(empresa, clientes, seed.montar_plano(DATA), senha=SENHA)

    def test_helena_login_ativa_contexto_cliente_e_abre_area_sem_gestao(self):
        empresa = Empresa.objects.get(cnpj=seed.CNPJ)
        helena = Cliente.objects.get(empresa=empresa, usuario__cpf=seed.CPF_HELENA)
        contextos = resolver_contextos(helena.usuario)
        self.assertEqual([(c['tipo_contexto'], c['empresa_id'], c['vinculo_id']) for c in contextos],
                         [('cliente', empresa.pk, helena.pk)])
        # O login oficial seleciona e ativa automaticamente o único contexto.
        resposta = self.client.post(reverse('usuarios:login'),
                                    {'cpf': seed.CPF_HELENA, 'senha': SENHA})
        self.assertRedirects(resposta, reverse('clientes:area'))
        self.assertEqual(int(self.client.session['_auth_user_id']), helena.usuario_id)
        self.assertEqual(self.client.session[CONTEXTO_SESSAO], {
            'tipo_contexto': 'cliente', 'empresa_id': empresa.pk, 'vinculo_id': helena.pk,
        })
        area = self.client.get(reverse('clientes:area'))
        self.assertEqual(area.status_code, 200)
        self.assertTemplateUsed(area, 'datasystem/cliente/area.html')
        self.assertEqual(area.context['cliente'], helena)
        self.assertEqual(validar_contexto_ativo(area.wsgi_request, 'cliente'), helena)
        self.assertEqual(self.client.get(reverse('empresas:area')).status_code, 403)
        administrador = empresa.membros.get(papel='ADMINISTRADOR')
        tentativa = self.client.post(reverse('usuarios:selecionar_contexto'),
                                     {'contexto': f'gestao:{administrador.pk}'})
        self.assertRedirects(tentativa, reverse('clientes:area'))
        self.assertEqual(self.client.session[CONTEXTO_SESSAO]['tipo_contexto'], 'cliente')

    def test_helena_inativa_ou_sem_senha_valida_impede_validacao_final(self):
        empresa = Empresa.objects.get(cnpj=seed.CNPJ)
        for falha in ('inativa', 'senha'):
            with self.subTest(falha=falha), transaction.atomic():
                usuario = get_user_model().objects.get(cpf=seed.CPF_HELENA)
                if falha == 'inativa':
                    usuario.is_active = False
                    usuario.save(update_fields=['is_active'])
                else:
                    usuario.set_unusable_password()
                    usuario.save(update_fields=['password'])
                clientes = {p.codigo: Cliente.objects.get(empresa=empresa, usuario__cpf=p.cpf)
                            for p in seed.populacao()}
                with self.assertRaisesRegex(CommandError, 'Helena não pode autenticar'):
                    seed._validar_contas_e_politica(empresa, clientes, SENHA)
                transaction.set_rollback(True)

    def test_helena_com_vinculo_cliente_incorreto_impede_validacao_final(self):
        empresa = Empresa.objects.get(cnpj=seed.CNPJ)
        clientes = {p.codigo: Cliente.objects.get(empresa=empresa, usuario__cpf=p.cpf)
                    for p in seed.populacao()}
        # Preserva nome/CPF e histórico, mas torna o vínculo incompatível com o tenant.
        outra = Empresa.objects.create(nome='Outra Empresa', slug='outra-helena', cnpj='11222333000181')
        Cliente.objects.filter(pk=clientes['I01'].pk).update(empresa=outra)
        with self.assertRaisesRegex(CommandError, 'Vínculo/contexto exclusivo'):
            seed._validar_contas_e_politica(empresa, clientes, SENHA)

    def test_retornos_historicos_e_combinacao_campanha_nivel_retorno(self):
        for codigo, campanha, nivel, pontos, final in (
            ('U01', False, 'Bronze', '172.39', '134.91'),
            ('I02', True, 'Prata', '1350', '255'),
            ('I03', False, 'Prata', '375', '255'),
        ):
            cpf = next(p.cpf for p in seed.populacao() if p.codigo == codigo)
            compra = Compra.objects.filter(cliente__usuario__cpf=cpf).latest('ocorrida_em')
            lote = compra.lote_pontos
            resultado = lote.beneficios_aplicados['resultado']
            self.assertFalse(resultado['ativo_antes'])
            self.assertTrue(resultado['retorno'])
            self.assertTrue(resultado['beneficios_nivel_aplicaveis'])
            self.assertEqual(resultado['nivel_anterior']['nome'], nivel)
            self.assertEqual(lote.aplicacoes_eventos.exists(), campanha)
            self.assertEqual(lote.pontos_concedidos, Decimal(pontos))
            self.assertEqual(Decimal(resultado['valor_final']), Decimal(final))

    def test_helena_consulta_simulacao_e_compra_real_isolada(self):
        empresa = Empresa.objects.get(cnpj=seed.CNPJ)
        dados = dict(credencial=empresa.credenciais_integracao.get(), loja_id=empresa.lojas.get(nome='Centro', cidade='Araras').pk,
                     cliente_cpf=seed.CPF_HELENA)
        t = seed.montar_plano(DATA).referencia
        antes = fotografia()
        with seed._relogio_resgate(t, modulo=consultas), seed._relogio_resgate(t, modulo=simulacoes):
            consulta = consultas.consultar_fidelidade_cliente(**dados)
            simulacao = simulacoes.simular_compra(**dados, valor=Decimal('300'))
        self.assertEqual(fotografia(), antes)
        self.assertFalse(consulta['atividade']['ativo'])
        self.assertEqual(consulta['nivel']['atual']['nome'], 'Ouro')
        self.assertTrue(consulta['nivel']['atual']['beneficios']['aplicaveis'])
        self.assertTrue(consulta['promocao_retorno']['aplicavel'])
        self.assertTrue(simulacao['atividade']['retorno'])
        self.assertEqual(simulacao['pontos']['total_estimado'], '405.0000')
        self.assertEqual(simulacao['valores']['final'], '240.00')
        with transaction.atomic():
            compra, criada = seed.registrar_compra(**dados, identificador_externo='DEMO-AO-VIVO',
                                                   valor=Decimal('300'), ocorrida_em=t)
            self.assertTrue(criada)
            self.assertEqual(compra.lote_pontos.pontos_concedidos, Decimal('405'))
            resultado = compra.lote_pontos.beneficios_aplicados['resultado']
            self.assertTrue(resultado['retorno'])
            self.assertEqual(Decimal(resultado['valor_final']), Decimal('240'))
            with seed._relogio_resgate(t, modulo=consultas):
                self.assertTrue(consultas.consultar_fidelidade_cliente(**dados)['atividade']['ativo'])
            transaction.set_rollback(True)
        self.assertEqual(fotografia(), antes)

    def test_estorno_preserva_historico_e_libera_saldo_consultado_simulado(self):
        estorno = EstornoResgate.objects.select_related('resgate', 'cliente__usuario').get()
        self.assertTrue(estorno.devolve_pontos_aplicado)
        self.assertEqual(estorno.resgate.pontos_resgatados, Decimal('200'))
        self.assertEqual(estorno.resgate.alocacoes.count(), 2)
        dados = dict(credencial=estorno.credencial_origem, loja_id=estorno.loja_id,
                     cliente_cpf=estorno.cliente.usuario.cpf)
        t = seed.montar_plano(DATA).referencia
        antes = fotografia()
        saldo = sum(l.pontos_concedidos for l in estorno.cliente.lotes_pontos.filter(expira_em__gt=t))
        with seed._relogio_resgate(t, modulo=consultas), seed._relogio_resgate(t):
            consulta = consultas.consultar_fidelidade_cliente(**dados)
            simulado = resgates.simular_resgate(**dados, pontos=200)
        self.assertEqual(Decimal(consulta['saldo']['pontos']), saldo)
        self.assertEqual(Decimal(simulado['saldo']['atual']), saldo)
        self.assertEqual(Decimal(simulado['saldo']['projetado']), saldo - 200)
        self.assertEqual(fotografia(), antes)

    def test_api_consulta_simulacoes_no_cenario_sem_mutar_historico(self):
        empresa = Empresa.objects.get(cnpj=seed.CNPJ)
        loja = empresa.lojas.get(nome='Centro', cidade='Araras')
        dados = dict(loja_id=loja.pk, cliente_cpf=seed.CPF_HELENA)
        api = APIClient()
        api.credentials(HTTP_X_API_KEY=self.chave)
        t = seed.montar_plano(DATA).referencia
        antes = assinatura_logica()
        with seed._relogio_resgate(t, modulo=consultas), seed._relogio_resgate(t, modulo=simulacoes), seed._relogio_resgate(t):
            consulta = api.get('/api/v1/clientes/fidelidade/', dados)
            compra = api.post('/api/v1/compras/simular/', {**dados, 'valor': '300.00'}, format='json')
            resgate = api.post('/api/v1/resgates/simular/', {**dados, 'pontos': 200}, format='json')
        for resposta in (consulta, compra, resgate):
            self.assertEqual(resposta.status_code, 200, resposta.content)
            self.assertIn('no-store', resposta['Cache-Control'])
        self.assertFalse(consulta.json()['atividade']['ativo'])
        self.assertTrue(consulta.json()['nivel']['atual']['beneficios']['aplicaveis'])
        self.assertEqual(compra.json()['pontos']['total_estimado'], '405.0000')
        self.assertEqual(resgate.json()['saldo'], {'atual': '3740.0000', 'projetado': '3540.0000'})
        self.assertEqual(assinatura_logica(), antes)

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
        self.assertEqual((resumo['compras'], resumo['clientes'], resumo['lojas']), (303, 36, 12))
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
            lambda: get_user_model().objects.create_user(seed.CPF_GESTOR, SENHA),
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

    def _verificar_rollback(self, alvo, real):
        antes = fotografia()

        def falhar(*args, **kwargs):
            real(*args, **kwargs)
            raise ValidationError('Falha depois de persistir pelo fluxo real')

        with patch(f'apps.fidelidade.seed_fatecalcados.{alvo}', side_effect=falhar):
            with self.assertRaises(ValidationError):
                seed.executar_seed(DATA, senha=SENHA)
        self.assertEqual(fotografia(), antes)
        self.assertIs(resgates.timezone, timezone)
        self.assertIs(estornos.timezone, timezone)
        self.assertIs(consultas.timezone, timezone)

    def test_falha_de_compra_reverte_tudo(self):
        self._verificar_rollback('registrar_compra', seed.registrar_compra)

    def test_falha_de_resgate_reverte_tudo(self):
        self._verificar_rollback('resgates.registrar_resgate', resgates.registrar_resgate)

    def test_falha_de_estorno_reverte_tudo(self):
        self._verificar_rollback('estornos.estornar_resgate', estornos.estornar_resgate)

    def test_falha_de_validacao_reverte_tudo(self):
        self._verificar_rollback('_resumo_e_validacao', seed._resumo_e_validacao)

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
                          LotePontos.objects.count(), Resgate.objects.count()), (1, 36, 303, 303, 8))
        self.assertIs(resgates.timezone, timezone)


class ArquivoCredencialUnitTests(SimpleTestCase):
    def test_exclusividade_e_permissao_mesmo_com_umask_restritiva(self):
        with TemporaryDirectory() as pasta:
            caminho = Path(pasta) / 'credencial'
            anterior = os.umask(0o777)
            try:
                with seed._arquivo_credencial(caminho) as gravar:
                    gravar('chave-ficticia-de-teste')
                    with self.assertRaises(CommandError):
                        gravar('outra')
            finally:
                os.umask(anterior)
            self.assertEqual(stat.S_IMODE(caminho.stat().st_mode), 0o600)
            with self.assertRaises(CommandError), seed._arquivo_credencial(caminho) as gravar:
                gravar('outra')
            self.assertEqual(caminho.read_text(), 'chave-ficticia-de-teste')

    def test_falha_de_escrita_remove_somente_arquivo_criado(self):
        with TemporaryDirectory() as pasta:
            caminho = Path(pasta) / 'credencial'
            with patch.object(seed.os, 'fsync', side_effect=OSError('falha')):
                with self.assertRaises(CommandError), seed._arquivo_credencial(caminho) as gravar:
                    gravar('chave-ficticia-de-teste')
            self.assertFalse(caminho.exists())
            caminho.write_text('preexistente')
            link = Path(pasta) / 'link'
            link.symlink_to(caminho)
            with self.assertRaises(CommandError), seed._arquivo_credencial(link) as gravar:
                gravar('outra')
            self.assertTrue(link.is_symlink())
            self.assertEqual(caminho.read_text(), 'preexistente')

    def test_falha_posterior_nao_remove_arquivo_substituido(self):
        with TemporaryDirectory() as pasta:
            caminho = Path(pasta) / 'credencial'
            outro = Path(pasta) / 'outro'
            outro.write_text('outro inode')
            with self.assertRaises(RuntimeError), seed._arquivo_credencial(caminho) as gravar:
                gravar('chave-ficticia-de-teste')
                outro.replace(caminho)
                raise RuntimeError('falha posterior')
            self.assertEqual(caminho.read_text(), 'outro inode')


@override_settings(PASSWORD_HASHERS=HASHERS)
class ArquivoCredencialSeedTests(TestCase):
    def test_comando_grava_chave_real_sem_expor_saida_ou_banco(self):
        with TemporaryDirectory() as pasta:
            caminho = Path(pasta) / 'credencial'
            saida, erro = StringIO(), StringIO()
            with patch.dict(os.environ, {'RETORNA_SEED_SENHA': SENHA,
                                         'RETORNA_SEED_CREDENCIAL_ARQUIVO': str(caminho)}):
                call_command('seed_fatecalcados', data_base=DATA.isoformat(), stdout=saida, stderr=erro)
            chave = caminho.read_text()
            credencial = autenticar_credencial(chave)
            self.assertIsNotNone(credencial)
            self.assertEqual(stat.S_IMODE(caminho.stat().st_mode), 0o600)
            resumo = json.loads(saida.getvalue())
            self.assertEqual(resumo['credencial_arquivo'], str(caminho))
            for segredo in (SENHA, chave, chave.split('.')[1]):
                self.assertNotIn(segredo, saida.getvalue() + erro.getvalue())
                self.assertNotIn(segredo, repr(fotografia()))

    def test_arquivo_preexistente_recusa_e_reverte_banco(self):
        antes = fotografia()
        with TemporaryDirectory() as pasta:
            caminho = Path(pasta) / 'credencial'
            caminho.write_text('preservar')
            with self.assertRaises(CommandError):
                seed.executar_seed(DATA, senha=SENHA, credencial_arquivo=caminho)
            self.assertEqual(caminho.read_text(), 'preservar')
        self.assertEqual(fotografia(), antes)

    def test_falha_de_escrita_reverte_banco_e_remove_arquivo(self):
        antes = fotografia()
        with TemporaryDirectory() as pasta:
            caminho = Path(pasta) / 'credencial'
            with patch.object(seed.os, 'fsync', side_effect=OSError('falha')):
                with self.assertRaises(CommandError):
                    seed.executar_seed(DATA, senha=SENHA, credencial_arquivo=caminho)
            self.assertFalse(caminho.exists())
        self.assertEqual(fotografia(), antes)

    def test_falha_de_validacao_final_remove_arquivo_e_reverte_banco(self):
        antes = fotografia()
        with TemporaryDirectory() as pasta:
            caminho = Path(pasta) / 'credencial'
            validar = seed._resumo_e_validacao

            def falhar(*args, **kwargs):
                validar(*args, **kwargs)
                self.assertTrue(caminho.exists())
                raise ValidationError('falha final')

            with patch.object(seed, '_resumo_e_validacao', side_effect=falhar):
                with self.assertRaises(ValidationError):
                    seed.executar_seed(DATA, senha=SENHA, credencial_arquivo=caminho)
            self.assertFalse(caminho.exists())
        self.assertEqual(fotografia(), antes)

    def test_sem_variavel_nao_abre_arquivo_nem_expoe_chave(self):
        saida = StringIO()
        with patch.dict(os.environ, {'RETORNA_SEED_SENHA': SENHA, 'RETORNA_SEED_CREDENCIAL_ARQUIVO': ''}):
            with patch.object(seed.os, 'open', side_effect=AssertionError('Não criar arquivo')):
                call_command('seed_fatecalcados', data_base=DATA.isoformat(), stdout=saida)
        self.assertNotIn('credencial_arquivo', json.loads(saida.getvalue()))
        self.assertNotIn(SENHA, saida.getvalue())


@override_settings(PASSWORD_HASHERS=HASHERS)
class CommitArquivoSeedTests(TransactionTestCase):
    def test_falha_de_commit_reverte_banco_e_remove_arquivo(self):
        with TemporaryDirectory() as pasta:
            caminho = Path(pasta) / 'credencial'
            with patch.object(connection, 'commit', side_effect=IntegrityError('commit recusado')):
                with self.assertRaises(IntegrityError):
                    seed.executar_seed(DATA, senha=SENHA, credencial_arquivo=caminho)
            self.assertFalse(caminho.exists())
        self.assertFalse(Empresa.objects.exists())
        self.assertFalse(get_user_model().objects.exists())
        self.assertFalse(Compra.objects.exists())
        self.assertFalse(EstornoResgate.objects.exists())
