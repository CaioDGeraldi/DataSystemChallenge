"""Contratos de apresentação; aparência e responsividade são verificadas no navegador."""
from html.parser import HTMLParser
from datetime import timedelta
from decimal import Decimal

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.template.loader import render_to_string
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.fidelidade.eventos import criar_evento
from apps.fidelidade.forms import EventoFidelidadeForm
from apps.fidelidade.models import EfeitoEvento
from apps.fidelidade.niveis import criar_nivel
from apps.usuarios.services import CONTEXTO_SESSAO

from .models import AcessoLoja, Empresa, Loja, MembroEmpresa
from .services import criar_convite, criar_credencial
from .forms import ConfiguracaoFidelidadeEmpresaForm


class Elementos(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.navegacao = []
        self.formularios = []
        self.em_gestao = False
        self.formulario = None
        self.apresentacoes = []
        self.regiao = None
        self.profundidade = 0
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if tag == 'div':
            if self.regiao is not None:
                self.profundidade += 1
            else:
                classes = attrs.get('class', '').split()
                for modo in ('desktop', 'mobile'):
                    if f'retorna-{modo}-presentation' in classes:
                        self.regiao = {'modo': modo, 'tags': [], 'texto': []}
                        self.apresentacoes.append(self.regiao)
                        self.profundidade = 1
        if self.regiao is not None:
            self.regiao['tags'].append((tag, attrs))
        if tag == 'nav':
            self.em_gestao = attrs.get('aria-label') == 'Navegação de Gestão'
        if tag == 'a' and self.em_gestao:
            self.navegacao.append(attrs)
        if tag == 'form':
            self.formulario = {'attrs': attrs, 'inputs': []}
            self.formularios.append(self.formulario)
        if tag == 'input' and self.formulario is not None:
            self.formulario['inputs'].append(attrs)

    def handle_endtag(self, tag):
        if tag == 'div' and self.regiao is not None:
            self.profundidade -= 1
            if self.profundidade == 0:
                self.regiao = None
        if tag == 'nav':
            self.em_gestao = False
        if tag == 'form':
            self.formulario = None

    def handle_data(self, data):
        if self.regiao is not None:
            self.regiao['texto'].append(data)


class InterfaceTests(TestCase):
    rotas_admin = (
        'empresas:area', 'empresas:membros', 'empresas:configuracao_empresa',
        'fidelidade:niveis', 'fidelidade:eventos', 'empresas:integracoes',
    )

    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nome='Empresa visual', slug='visual', cnpj='11222333000181')
        cls.admin = get_user_model().objects.create_user('52998224725')
        cls.gestor = get_user_model().objects.create_user('11144477735')
        cls.membro = MembroEmpresa.objects.create(
            usuario=cls.admin, empresa=cls.empresa, papel=MembroEmpresa.Papel.ADMINISTRADOR,
        )
        cls.membro_gestor = MembroEmpresa.objects.create(
            usuario=cls.gestor, empresa=cls.empresa, papel=MembroEmpresa.Papel.GESTOR,
        )
        cls.loja = Loja.objects.create(empresa=cls.empresa, nome='Unidade permitida', cidade='Araras')
        cls.restrita = Loja.objects.create(empresa=cls.empresa, nome='Unidade restrita', cidade='Limeira')
        AcessoLoja.objects.create(membro=cls.membro_gestor, loja=cls.loja)
        cls.cliente = Cliente.objects.create(usuario=cls.admin, empresa=cls.empresa)

    def entrar(self, usuario=None, vinculo=None, tipo='gestao', client=None):
        client = client or self.client
        client.force_login(usuario or self.admin)
        vinculo = vinculo or self.membro
        session = client.session
        session[CONTEXTO_SESSAO] = {
            'tipo_contexto': tipo, 'empresa_id': self.empresa.pk, 'vinculo_id': vinculo.pk,
        }
        session.save()

    def pagina(self, rota, **kwargs):
        resposta = self.client.get(reverse(rota, kwargs=kwargs))
        self.assertEqual(resposta.status_code, 200)
        return resposta, Elementos(resposta.content.decode())

    def test_home_publica_e_sem_dashboard(self):
        resposta, html = self.pagina('usuarios:home')
        self.assertEqual(reverse('usuarios:home'), '/')
        for destino in ('usuarios:login', 'usuarios:para_empresas'):
            self.assertTrue(any(t == 'a' and a.get('href') == reverse(destino) for t, a in html.tags))
        self.assertContains(resposta, 'Como funciona para você')
        self.assertContains(resposta, 'Acumule pontos')
        self.assertNotContains(resposta, 'Criar empresa')
        self.assertNotContains(resposta, 'Dashboard')
        self.assertNotContains(resposta, 'retorna-illustration-frame')
        self.assertEqual(html.navegacao, [])

    def test_home_multiplos_contextos_usa_selecao_existente(self):
        self.client.force_login(self.admin)
        resposta, html = self.pagina('usuarios:home')
        self.assertEqual(len(resposta.context['contextos']), 2)
        self.assertContains(resposta, 'Administrador')
        self.assertContains(resposta, 'Cliente')
        selecoes = [f for f in html.formularios if f['attrs'].get('action') == reverse('usuarios:selecionar_contexto')]
        self.assertEqual(len(selecoes), 2)
        for form in selecoes:
            self.assertEqual(form['attrs']['method'], 'post')
            self.assertTrue(any(i.get('name') == 'csrfmiddlewaretoken' for i in form['inputs']))
        self.assertNotIn(CONTEXTO_SESSAO, self.client.session)

    def test_home_contexto_unico_e_zero_nao_redirecionam(self):
        self.client.force_login(self.gestor)
        resposta, _ = self.pagina('usuarios:home')
        self.assertEqual(len(resposta.context['contextos']), 1)
        self.assertContains(resposta, 'Gestor')
        self.assertContains(resposta, 'Continuar para gestão')
        self.membro_gestor.ativo = False
        self.membro_gestor.save()
        resposta, _ = self.pagina('usuarios:home')
        self.assertContains(resposta, 'Você ainda não possui uma Empresa ou programa disponível.')
        self.assertContains(resposta, 'Criar empresa')

    def test_home_cliente_sem_vinculo_administrativo(self):
        self.membro.ativo = False
        self.membro.save()
        self.client.force_login(self.admin)
        resposta, html = self.pagina('usuarios:home')
        self.assertContains(resposta, 'Continuar como Cliente')
        self.assertNotContains(resposta, 'Continuar para gestão')
        self.assertEqual(html.navegacao, [])

    def test_home_preserva_contexto_ativo_e_restricao_de_troca(self):
        self.entrar()
        antes = dict(self.client.session[CONTEXTO_SESSAO])
        resposta, html = self.pagina('usuarios:home')
        self.assertTrue(any(t == 'a' and a.get('href') == reverse('empresas:area') for t, a in html.tags))
        self.assertFalse(any(f['attrs'].get('action') == reverse('usuarios:selecionar_contexto') for f in html.formularios))
        self.assertContains(resposta, 'encerre a sessão')
        self.assertEqual(self.client.session[CONTEXTO_SESSAO], antes)

    def test_para_empresas_publica_com_acoes_reais(self):
        resposta, html = self.pagina('usuarios:para_empresas')
        self.assertEqual(reverse('usuarios:para_empresas'), '/para-empresas/')
        self.assertContains(resposta, 'Retorna para empresas')
        for destino in ('usuarios:login', 'empresas:onboarding'):
            self.assertTrue(any(t == 'a' and a.get('href') == reverse(destino) for t, a in html.tags))
        for titulo in ('Pontos por compra', 'Campanhas', 'Níveis', 'Resgates', 'Várias lojas', 'Gestão da equipe'):
            self.assertContains(resposta, titulo)
        self.assertNotContains(resposta, 'retorna-illustration-frame')
        self.assertNotContains(resposta, 'Dashboard')
        self.assertEqual(html.navegacao, [])

    def test_storyset_onboarding_decorativo_com_variantes(self):
        from django.templatetags.static import static
        resposta, html = self.pagina('empresas:onboarding')
        for tema in ('light', 'dark'):
            caminho = f'illustrations/welcome_onboarding-{tema}.svg'
            self.assertEqual(finders.find(caminho), str(settings.BASE_DIR / 'frontend' / 'dist' / caminho))
            imagem = next(a for t, a in html.tags if t == 'img' and a.get('src') == static(caminho))
            self.assertEqual(imagem['alt'], '')
        self.assertTrue(any(t == 'figure' and a.get('aria-hidden') == 'true' for t, a in html.tags))
        self.assertContains(resposta, 'Ilustrações por Storyset / Freepik')
        self.assertIsNone(finders.find('illustrations/form_guidance.svg'))
        for rota, kwargs in [('usuarios:login', {}), ('clientes:cadastro', {'slug': self.empresa.slug})]:
            resposta, _ = self.pagina(rota, **kwargs)
            self.assertNotContains(resposta, 'retorna-illustration-frame')
            self.assertNotContains(resposta, 'retorna-form-layout--illustrated')

    def test_configuracao_secoes_diretas_e_fallback(self):
        self.entrar()
        resposta, html = self.pagina('empresas:configuracao_empresa')
        self.assertNotContains(resposta, 'Exibir tudo</button>')
        self.assertFalse(any('data-form-mode-toggle' in a for _, a in html.tags))
        formularios = [f for f in html.formularios if 'data-form-sections' in f['attrs']]
        self.assertEqual(len(formularios), 1)
        triggers = [a for t, a in html.tags if 'data-form-section-trigger' in a]
        etapas = [a for t, a in html.tags if 'data-form-step' in a]
        self.assertEqual(len(triggers), len(etapas))
        self.assertEqual(len(etapas), 3)
        self.assertEqual({a['aria-controls'] for a in triggers}, {a['id'] for a in etapas})
        self.assertTrue(all(a['type'] == 'button' for a in triggers))
        self.assertTrue(all('hidden' not in a and 'disabled' not in a for a in etapas))
        self.assertEqual(sum('data-form-final-submit' in a for _, a in html.tags), 1)
        resposta = self.client.post(reverse('empresas:configuracao_empresa'), {})
        erros = Elementos(resposta.content.decode())
        self.assertTrue(any('data-step-has-errors' in a for _, a in erros.tags))
        self.assertContains(resposta, 'Revise os campos')

    def test_busca_deriva_da_mesma_navegacao_autorizada(self):
        for usuario, membro in [(self.admin, self.membro), (self.gestor, self.membro_gestor)]:
            with self.subTest(usuario=usuario.pk):
                self.entrar(usuario=usuario, vinculo=membro)
                resposta, html = self.pagina('empresas:area')
                links_busca = []
                # Parser da região isolada mantém o contrato sem depender de estilos.
                fragmento = resposta.content.decode().split('id="navigation-search-results"', 1)[1].split('</ul>', 1)[0]
                links_busca = [a['href'] for t, a in Elementos(fragmento).tags if t == 'a']
                self.assertEqual(links_busca, [a['href'] for a in html.navegacao])
                self.assertTrue(any(a.get('aria-keyshortcuts') == 'Alt+K' for _, a in html.tags))
                self.assertTrue(any(t == 'input' and a.get('type') == 'search' for t, a in html.tags))
                if usuario == self.gestor:
                    self.assertEqual(links_busca, [reverse('empresas:area')])

    def test_preferencias_locais_landmarks_e_logout(self):
        self.entrar()
        resposta, html = self.pagina('empresas:area')
        self.assertTrue(any(t == 'html' and a.get('lang') == 'pt-BR' and
                            a.get('data-retorna-theme') == 'light' for t, a in html.tags))
        self.assertEqual(sum(t == 'main' for t, _ in html.tags), 1)
        self.assertTrue(any(t == 'main' and a.get('id') == 'conteudo' for t, a in html.tags))
        self.assertTrue(any(t == 'a' and a.get('href') == '#conteudo' for t, a in html.tags))
        self.assertTrue(any(t == 'button' and 'data-appearance-open' in a for t, a in html.tags))
        self.assertTrue(any(t == 'dialog' and a.get('aria-labelledby') == 'appearance-title' for t, a in html.tags))
        for name, values in [('theme', {'system', 'light', 'dark'}),
                             ('fontScale', {'100', '110', '120'}),
                             ('formMode', {'steps', 'all'})]:
            self.assertEqual({a.get('value') for t, a in html.tags
                              if t == 'input' and a.get('name') == name}, values)
        self.assertTrue(any(t == 'button' and 'data-appearance-reset' in a for t, a in html.tags))
        logout = [f for f in html.formularios if f['attrs'].get('action') == reverse('usuarios:logout')]
        self.assertEqual(len(logout), 1)
        self.assertEqual(logout[0]['attrs']['method'], 'post')
        self.assertTrue(any(i.get('name') == 'csrfmiddlewaretoken' for i in logout[0]['inputs']))
        self.assertContains(resposta, 'Aparência e acessibilidade')

    def test_admin_tem_seis_entradas_e_secao_ativa(self):
        self.entrar()
        for rota in self.rotas_admin:
            with self.subTest(rota=rota):
                resposta, html = self.pagina(rota)
                self.assertTemplateUsed(resposta, 'datasystem/gestao_base.html')
                self.assertEqual([a['href'] for a in html.navegacao], [reverse(r) for r in self.rotas_admin])
                self.assertEqual([a['href'] for a in html.navegacao if a.get('aria-current') == 'page'], [reverse(rota)])
                self.assertNotContains(resposta, reverse('empresas:onboarding'))

    def test_gestor_so_recebe_lojas_permitidas(self):
        self.entrar(self.gestor, self.membro_gestor)
        resposta, html = self.pagina('empresas:area')
        self.assertEqual([a['href'] for a in html.navegacao], [reverse('empresas:area')])
        self.assertContains(resposta, self.loja.nome)
        self.assertNotContains(resposta, self.restrita.nome)
        for rota in self.rotas_admin[1:]:
            self.assertNotContains(resposta, reverse(rota))
            self.assertEqual(self.client.get(reverse(rota)).status_code, 403)
        self.assertNotContains(resposta, reverse('empresas:onboarding'))

    def test_lojas_em_duas_apresentacoes_com_engrenagem_acessivel(self):
        self.entrar()
        _, html = self.pagina('empresas:area')
        self.assertEqual([p['modo'] for p in html.apresentacoes], ['desktop', 'mobile'])
        for regiao in html.apresentacoes:
            self.assertIn(self.loja.nome, ''.join(regiao['texto']))
            self.assertIn(self.loja.cidade, ''.join(regiao['texto']))
            link = next(a for t, a in regiao['tags'] if t == 'a' and a.get('href') == reverse('empresas:configuracao_loja', args=[self.loja.pk]))
            self.assertEqual(link['aria-label'], f'Configurar {self.loja.nome}')
            self.assertEqual(link['title'], 'Configurar')
            self.assertNotIn('Configuração', ''.join(regiao['texto']))
        self.entrar(self.gestor, self.membro_gestor)
        _, html = self.pagina('empresas:area')
        for regiao in html.apresentacoes:
            self.assertNotIn(self.restrita.nome, ''.join(regiao['texto']))
            self.assertFalse(any(t == 'a' and a.get('title') == 'Configurar' for t, a in regiao['tags']))

    def test_breadcrumb_profundo_compactavel_sem_link_no_atual_ou_ellipsis(self):
        ancestrais = [
            {'rotulo': 'Lojas', 'url': reverse('empresas:area')},
            {'rotulo': 'Membros', 'url': reverse('empresas:membros')},
        ]
        for quantidade in (1, 2, 3):
            with self.subTest(quantidade=quantidade):
                breadcrumbs = ancestrais[:quantidade - 1] + [{'rotulo': 'Atual com nome longo', 'url': None}]
                html = render_to_string('datasystem/includes/topbar.html', {'breadcrumbs': breadcrumbs})
                tags = Elementos(html).tags
                self.assertTrue(any(t == 'span' and a.get('aria-current') == 'page' for t, a in tags))
                self.assertFalse(any(t == 'a' and a.get('aria-current') == 'page' for t, a in tags))
                for item in breadcrumbs[:-1]:
                    self.assertTrue(any(t == 'a' and a.get('href') == item['url'] for t, a in tags))
                marcadores = [(t, a) for t, a in tags if 'retorna-breadcrumb-compact-ellipsis' in a.get('class', '').split()]
                self.assertEqual(len(marcadores), int(quantidade > 2))
                if marcadores:
                    self.assertEqual(marcadores[0][0], 'li')
                    self.assertEqual(marcadores[0][1].get('aria-hidden'), 'true')
                    self.assertNotIn('tabindex', marcadores[0][1])
                    self.assertIn('retorna-breadcrumb-list-compactable', html)

    def test_breadcrumbs_e_retorno_das_paginas_filhas(self):
        self.entrar()
        for rota, kwargs, pai, rotulo in (
            ('empresas:criar_loja', {}, 'empresas:area', 'Nova Loja'),
            ('empresas:configuracao_loja', {'loja_id': self.loja.pk}, 'empresas:area', f'Configuração — {self.loja.nome}'),
            ('empresas:convidar_membro', {}, 'empresas:membros', 'Convidar membro'),
            ('empresas:nova_integracao', {}, 'empresas:integracoes', 'Criar chave de integração'),
            ('fidelidade:novo_evento', {}, 'fidelidade:eventos', 'Criar campanha'),
            ('fidelidade:novo_nivel', {}, 'fidelidade:niveis', 'Criar nível'),
        ):
            with self.subTest(rota=rota):
                resposta, _ = self.pagina(rota, **kwargs)
                self.assertEqual(resposta.context['back_url'], reverse(pai))
                self.assertEqual(resposta.context['breadcrumbs'][-1], {'rotulo': rotulo, 'url': None})
                fragmento = render_to_string('datasystem/includes/topbar.html', {
                    'breadcrumbs': resposta.context['breadcrumbs'], 'user': self.admin,
                })
                elementos = Elementos(fragmento)
                self.assertTrue(any(t == 'a' and a.get('href') == reverse(pai) for t, a in elementos.tags))
                atuais = [(t, a) for t, a in elementos.tags if a.get('aria-current') == 'page']
                self.assertEqual(len(atuais), 1)
                self.assertEqual(atuais[0][0], 'span')
                self.assertContains(resposta, self.empresa.nome)
                retorno = render_to_string('datasystem/includes/back_link.html', {
                    'back_url': resposta.context['back_url'], 'back_label': resposta.context['back_label'],
                })
                self.assertIn(resposta.context['back_label'], retorno)
                self.assertTrue(any(t == 'a' and a.get('href') == reverse(pai) for t, a in Elementos(retorno).tags))
                if rota == 'empresas:configuracao_loja':
                    self.assertEqual(resposta.context['back_label'], 'Voltar para Lojas')

    def test_cliente_com_vinculo_administrativo_nao_recebe_shell_gestao(self):
        self.entrar(vinculo=self.cliente, tipo='cliente')
        resposta, html = self.pagina('clientes:area')
        self.assertEqual(html.navegacao, [])
        self.assertTemplateNotUsed(resposta, 'datasystem/gestao_base.html')
        self.assertNotContains(resposta, reverse('empresas:onboarding'))
        self.assertContains(resposta, 'retorna/brand/retorna-logo-light.svg')

    def test_formularios_publicos_permanecem_publicos(self):
        for rota, kwargs in (
            ('usuarios:login', {}), ('empresas:onboarding', {}),
            ('clientes:cadastro', {'slug': self.empresa.slug}),
        ):
            with self.subTest(rota=rota):
                resposta, html = self.pagina(rota, **kwargs)
                self.assertEqual(html.navegacao, [])
                self.assertTemplateNotUsed(resposta, 'datasystem/gestao_base.html')

    def test_formularios_administrativos_e_csrf(self):
        self.entrar()
        for rota, kwargs in (
            ('empresas:criar_loja', {}), ('empresas:convidar_membro', {}),
            ('empresas:configuracao_empresa', {}), ('empresas:nova_integracao', {}),
            ('empresas:configuracao_loja', {'loja_id': self.loja.pk}),
            ('fidelidade:novo_nivel', {}), ('fidelidade:novo_evento', {}),
        ):
            with self.subTest(rota=rota):
                resposta, html = self.pagina(rota, **kwargs)
                self.assertTemplateUsed(resposta, 'datasystem/gestao_base.html')
                self.assertTrue(html.formularios)
                for form in html.formularios:
                    self.assertEqual(form['attrs'].get('method', '').lower(), 'post')
                    self.assertTrue(any(i.get('name') == 'csrfmiddlewaretoken' for i in form['inputs']))

    def test_campanha_aplicacao_checkboxes_e_erros_preservados(self):
        self.entrar()
        resposta, html = self.pagina('fidelidade:novo_evento')
        self.assertContains(resposta, 'Aplicação')
        self.assertContains(resposta, 'Toda a empresa')
        self.assertContains(resposta, 'Lojas específicas')
        self.assertContains(resposta, '1,50 = 50% a mais')
        self.assertTrue(any('data-campaign-stores' in a and 'hidden' not in a for _, a in html.tags))
        self.assertTrue(any(t == 'option' and a.get('value') == 'EMPRESA' for t, a in html.tags))
        self.assertTrue(any(t == 'option' and a.get('value') == 'LOJAS' for t, a in html.tags))
        checkboxes = [a for t, a in html.tags if t == 'input' and a.get('name') == 'lojas']
        self.assertEqual({a['value'] for a in checkboxes}, {str(self.loja.pk), str(self.restrita.pk)})
        self.assertTrue(all(a.get('type') == 'checkbox' and 'disabled' not in a for a in checkboxes))
        inicio = timezone.now() + timedelta(days=1)
        dados = {'nome': 'Campanha', 'inicio_em': inicio.isoformat(),
                 'fim_em': (inicio + timedelta(days=1)).isoformat(),
                 'escopo': 'LOJAS', 'lojas': [self.loja.pk], 'multiplicador': '1.50'}
        form = EventoFidelidadeForm(dados, empresa=self.empresa)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(list(form.cleaned_data['lojas']), [self.loja])
        dados['escopo'] = 'EMPRESA'
        resposta = self.client.post(reverse('fidelidade:novo_evento'), dados)
        self.assertContains(resposta, 'data-has-errors="true"')
        self.assertTrue(resposta.context['form'].errors.get('lojas'))

    def test_arredondamento_rotulos_sem_mudar_values(self):
        campo = ConfiguracaoFidelidadeEmpresaForm().fields['modo_arredondamento_pontos']
        self.assertEqual(campo.label, 'Arredondamento dos pontos')
        self.assertEqual(list(campo.choices), [('HALF_UP', 'Mais próximo (5 para cima)'),
                                              ('DOWN', 'Sempre para baixo'), ('UP', 'Sempre para cima')])
        self.entrar()
        resposta, html = self.pagina('empresas:configuracao_empresa')
        for valor, rotulo in campo.choices:
            self.assertContains(resposta, rotulo)
            self.assertTrue(any(t == 'option' and a.get('value') == valor for t, a in html.tags))

    def test_formularios_compostos_campos_etapas_e_fallback(self):
        self.entrar()
        for rota, rotulos in (
            ('empresas:onboarding', ['Empresa', 'Primeira Loja']),
            ('empresas:convidar_membro', ['Pessoa', 'Acesso']),
            ('empresas:nova_integracao', ['Identificação', 'Acesso']),
            ('empresas:configuracao_empresa', ['Acúmulo de pontos', 'Validade e atividade', 'Resgate']),
            ('fidelidade:novo_evento', ['Campanha', 'Aplicação', 'Pontuação']),
        ):
            with self.subTest(rota=rota):
                resposta, html = self.pagina(rota)
                # Logout pertence ao shell; há exatamente um formulário de dados.
                forms = [f for f in html.formularios if 'data-composed-form' in f['attrs']]
                self.assertEqual(len(forms), 1)
                self.assertNotIn('data-composed-form-initial-mode', forms[0]['attrs'])
                self.assertTrue(any(i.get('name') == 'csrfmiddlewaretoken' for i in forms[0]['inputs']))
                etapas = [a for t, a in html.tags if t == 'fieldset' and 'data-form-step' in a]
                self.assertEqual([e['data-step-label'] for e in etapas], rotulos)
                secoes = rota == 'empresas:configuracao_empresa'
                self.assertTrue(any(t == 'ol' and a.get('aria-label') ==
                                    ('Seções do formulário' if secoes else 'Etapas do formulário')
                                    for t, a in html.tags))
                for numero, rotulo in enumerate(rotulos, 1):
                    termo = 'Seção' if secoes else 'Etapa'
                    self.assertContains(resposta, f'<legend tabindex="-1">{termo} {numero} — {rotulo}</legend>', html=True)
                self.assertTrue(all('hidden' not in e and 'disabled' not in e for e in etapas))
                self.assertEqual(sum(t == 'legend' and a.get('tabindex') == '-1' for t, a in html.tags), len(rotulos))
                self.assertTrue(any(t == 'ol' and 'data-form-step-list' in a for t, a in html.tags))
                hooks = ['data-form-step-previous', 'data-form-step-next']
                if rota != 'empresas:configuracao_empresa':
                    hooks.append('data-form-mode-toggle')
                for hook in hooks:
                    self.assertTrue(any(t == 'button' and hook in a and 'hidden' in a and a.get('type') == 'button' for t, a in html.tags))
                self.assertTrue(any('data-form-step-status' in a and a.get('aria-live') == 'polite' for _, a in html.tags))
                self.assertTrue(any('data-form-final-submit' in a and 'hidden' not in a and 'disabled' not in a for _, a in html.tags))
                nomes = [a['name'] for t, a in html.tags if t in ('input', 'select', 'textarea') and a.get('name') in resposta.context['form'].fields]
                self.assertEqual(set(nomes), set(resposta.context['form'].fields))
                if rota == 'empresas:onboarding':
                    self.assertContains(resposta, 'retorna-illustration-frame')
                    self.assertContains(resposta, 'Ilustrações por Storyset / Freepik')
                else:
                    self.assertNotContains(resposta, 'retorna-illustration-frame')
                    self.assertNotContains(resposta, 'retorna-form-layout--illustrated')

    def test_onboarding_publico_e_cadastro_possuem_grupos_reais(self):
        for rota, kwargs, quantidade in (
            ('empresas:onboarding', {}, 3),
            ('clientes:cadastro', {'slug': self.empresa.slug}, 2),
        ):
            resposta, html = self.pagina(rota, **kwargs)
            self.assertEqual(sum('data-form-step' in a for _, a in html.tags), quantidade)
            self.assertEqual(len(html.formularios), 1)

    def test_erro_server_side_marca_etapa_e_resumo(self):
        self.entrar()
        resposta = self.client.post(reverse('fidelidade:novo_evento'), {
            'nome': 'Teste', 'inicio_em': '2026-09-01T12:00', 'fim_em': '2026-09-02T12:00',
            'escopo': 'LOJAS', 'multiplicador': '2',
        })
        html = Elementos(resposta.content.decode())
        etapas = [a for _, a in html.tags if 'data-step-has-errors' in a]
        self.assertEqual([e['data-step-label'] for e in etapas], ['Aplicação'])
        resumo = next(a for _, a in html.tags if 'data-form-error-summary' in a)
        self.assertEqual((resumo['role'], resumo['tabindex']), ('alert', '-1'))
        self.assertContains(resposta, 'Selecione ao menos uma Loja.')

    def test_formularios_simples_nao_recebem_wizard(self):
        self.entrar()
        for rota, kwargs in (
            ('empresas:criar_loja', {}), ('fidelidade:novo_nivel', {}),
            ('empresas:configuracao_loja', {'loja_id': self.loja.pk}),
        ):
            resposta, html = self.pagina(rota, **kwargs)
            self.assertFalse(any('data-composed-form' in a for _, a in html.tags))
            self.assertContains(resposta, 'retorna-form-layout')
            self.assertNotContains(resposta, 'retorna-illustration-frame')
            self.assertNotContains(resposta, 'retorna-form-layout--illustrated')
        self.client.logout()
        _, html = self.pagina('usuarios:login')
        self.assertFalse(any('data-composed-form' in a for _, a in html.tags))

    def test_staticfiles_e_referencias(self):
        self.entrar()
        resposta, _ = self.pagina('empresas:area')
        for caminho in ('retorna.css', 'retorna/brand/retorna-logo-dark.svg', 'retorna/brand/retorna-icon.svg'):
            self.assertIsNotNone(finders.find(caminho))
            self.assertContains(resposta, caminho)
        self.assertIn(settings.BASE_DIR / 'frontend' / 'dist', settings.STATICFILES_DIRS)
        self.assertEqual(finders.find('retorna.css'), str(settings.BASE_DIR / 'frontend' / 'dist' / 'retorna.css'))
        self.assertIsNotNone(finders.find('retorna/brand/retorna-logo-light.svg'))
        self.assertIsNotNone(finders.find('retorna/brand/retorna-symbol.svg'))
        resposta, html = self.pagina('empresas:nova_integracao')
        self.assertContains(resposta, 'retorna.js')
        self.assertIsNotNone(finders.find('retorna.js'))
        ids = {attrs.get('id') for _, attrs in html.tags}
        self.assertTrue({'id_escopo', 'id_lojas', 'selecao-lojas'} <= ids)

    def test_403_sem_contexto_valido(self):
        self.client.force_login(self.admin)
        resposta = self.client.get(reverse('empresas:area'))
        self.assertEqual(resposta.status_code, 403)
        self.assertTemplateUsed(resposta, '403.html')
        self.assertEqual(Elementos(resposta.content.decode()).navegacao, [])

    def test_logout_e_acao_preservam_post_csrf(self):
        protegido = Client(enforce_csrf_checks=True)
        self.entrar(client=protegido)
        self.assertEqual(protegido.get(reverse('usuarios:logout')).status_code, 405)
        self.assertEqual(protegido.post(reverse('usuarios:logout')).status_code, 403)
        self.assertEqual(protegido.post(reverse('empresas:criar_loja'), {'nome': 'Nova', 'cidade': 'Araras'}).status_code, 403)
        resposta = protegido.get(reverse('empresas:area'))
        html = Elementos(resposta.content.decode())
        logout = next(f for f in html.formularios if f['attrs'].get('action') == reverse('usuarios:logout'))
        token = next(i['value'] for i in logout['inputs'] if i.get('name') == 'csrfmiddlewaretoken')
        self.assertEqual(protegido.post(reverse('usuarios:logout'), {'csrfmiddlewaretoken': token}).status_code, 302)

    def test_acoes_das_listagens_continuam_post_com_csrf(self):
        self.entrar()
        request = RequestFactory().get('/gestao/')
        request.user = self.admin
        request.session = self.client.session
        nivel = criar_nivel(request, nome='Inicial', pontos_minimos=Decimal('0'))
        credencial, _ = criar_credencial(request, nome='PDV', escopo='EMPRESA')
        convite, _ = criar_convite(request, cpf='12345678909', papel='ADMINISTRADOR')
        inicio = timezone.now() + timedelta(days=1)
        evento = criar_evento(
            request, nome='Campanha', descricao='', inicio_em=inicio,
            fim_em=inicio + timedelta(days=1), escopo='EMPRESA',
            efeitos=[{'tipo': EfeitoEvento.Tipo.MULTIPLICADOR_PONTOS, 'valor': Decimal('2')}],
        )
        protegido = Client(enforce_csrf_checks=True)
        self.entrar(client=protegido)
        for lista, acao, identificador, texto in (
            ('fidelidade:niveis', 'fidelidade:excluir_nivel', nivel.pk, 'Inicial'),
            ('fidelidade:eventos', 'fidelidade:cancelar_evento', evento.pk, 'Campanha'),
            ('empresas:integracoes', 'empresas:desativar_integracao', credencial.pk, credencial.identificador),
            ('empresas:membros', 'empresas:revogar_convite', convite.pk, '123.456.789-09'),
        ):
            with self.subTest(acao=acao):
                _, html = self.pagina(lista)
                url = reverse(acao, args=[identificador])
                forms = [f for f in html.formularios if f['attrs'].get('action') == url]
                self.assertEqual(len(forms), 2)
                for form in forms:
                    self.assertEqual(form['attrs']['method'].lower(), 'post')
                    self.assertTrue(any(i.get('name') == 'csrfmiddlewaretoken' for i in form['inputs']))
                regioes = [p for p in html.apresentacoes if any(t == 'form' and a.get('action') == url for t, a in p['tags'])]
                self.assertEqual([p['modo'] for p in regioes], ['desktop', 'mobile'])
                for regiao in regioes:
                    self.assertIn(texto, ''.join(regiao['texto']))
                    if lista == 'fidelidade:niveis':
                        self.assertTrue(any(t == 'a' and a.get('aria-label') == 'Editar nível Inicial'
                                            and a.get('href') == reverse('fidelidade:editar_nivel', args=[nivel.pk])
                                            for t, a in regiao['tags']))
                        self.assertTrue(any(t == 'button' and a.get('aria-label') == 'Excluir nível Inicial'
                                            for t, a in regiao['tags']))
                        self.assertNotIn('Editar Inicial', ''.join(regiao['texto']))
                        self.assertNotIn('Excluir Inicial', ''.join(regiao['texto']))
                if lista == 'empresas:membros':
                    for regiao in html.apresentacoes[:2]:
                        self.assertIn('529.982.247-25', ''.join(regiao['texto']))
                self.assertEqual(protegido.get(url).status_code, 405)
                self.assertEqual(protegido.post(url).status_code, 403)
        resposta, _ = self.pagina('fidelidade:editar_nivel', nivel_id=nivel.pk)
        self.assertTemplateUsed(resposta, 'datasystem/gestao_base.html')

    def test_listagens_vazias_nao_criam_cards_mobile(self):
        self.entrar()
        for rota in ('fidelidade:niveis', 'fidelidade:eventos', 'empresas:integracoes'):
            with self.subTest(rota=rota):
                _, html = self.pagina(rota)
                mobile = next(p for p in html.apresentacoes if p['modo'] == 'mobile')
                self.assertFalse(any('retorna-mobile-card' in a.get('class', '').split() for _, a in mobile['tags']))
                self.assertIn('Nenhum', ''.join(mobile['texto']))

    def test_messages_preservam_texto_tipo_e_semantica(self):
        from django.contrib.messages import constants
        from django.contrib.messages.storage.base import Message

        for nivel, rotulo, papel in (
            (constants.SUCCESS, 'Sucesso', 'status'), (constants.ERROR, 'Erro', 'alert'),
            (constants.WARNING, 'Atenção', 'status'), (constants.INFO, 'Informação', 'status'),
        ):
            with self.subTest(nivel=nivel):
                html = render_to_string('datasystem/includes/mensagens.html', {
                    'messages': [Message(nivel, 'Texto preservado')],
                })
                self.assertIn(rotulo, html)
                self.assertIn('Texto preservado', html)
                self.assertTrue(any(a.get('role') == papel for _, a in Elementos(html).tags))

    def test_renderer_preserva_widgets_erros_labels_e_ajuda(self):
        class Exemplo(forms.Form):
            segredo = forms.CharField(widget=forms.HiddenInput)
            nome = forms.CharField(help_text='Ajuda legível')
            aceite = forms.BooleanField(required=False)
            escolha = forms.ChoiceField(choices=[('a', 'A')], widget=forms.RadioSelect)
            varias = forms.MultipleChoiceField(choices=[('a', 'A')])

        form = Exemplo(data={'segredo': 'interno', 'escolha': 'a', 'varias': ['a']})
        form.is_valid()
        form.add_error(None, 'Erro geral visível')
        html = render_to_string('datasystem/includes/campos_formulario.html', {'form': form})
        elementos = Elementos(html)
        self.assertIn('Erro geral visível', html)
        self.assertIn(str(form.errors['nome'][0]), html)
        self.assertIn('Ajuda legível', html)
        inputs = {a['name']: a for t, a in elementos.tags if t == 'input'}
        self.assertEqual(inputs['segredo']['type'], 'hidden')
        self.assertEqual(inputs['aceite']['type'], 'checkbox')
        self.assertEqual(inputs['escolha']['type'], 'radio')
        self.assertIn('id_nome_helptext', inputs['nome']['aria-describedby'])
        self.assertTrue(any(t == 'label' and a.get('for') == 'id_nome' for t, a in elementos.tags))
        self.assertTrue(any(t == 'select' and 'multiple' in a for t, a in elementos.tags))
