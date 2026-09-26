import json
from decimal import Decimal
from unittest.mock import patch

from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.empresas.models import ConfiguracaoFidelidadeEmpresa
from apps.usuarios.services import CONTEXTO_SESSAO

from .eventos import cancelar_evento
from .models import AplicacaoEfeitoEventoLote, Compra, EventoFidelidade, LotePontos
from .test_eventos import DadosEventos


class GestaoEventoTests(DadosEventos, TestCase):
    def login(self, client=None):
        client = client or self.client
        client.force_login(self.usuario)
        sessao = client.session
        sessao[CONTEXTO_SESSAO] = self.request().session[CONTEXTO_SESSAO]
        sessao.save()

    def payload(self, **mudancas):
        return dict({'nome': 'Campanha', 'descricao': 'Temporária', 'inicio_em': self.instante.isoformat(),
                     'fim_em': self.instante.replace(day=24).isoformat(), 'escopo': 'EMPRESA',
                     'multiplicador': '1.0025'}, **mudancas)

    def test_admin_cria_lista_cancela_com_empresa_do_contexto(self):
        self.login()
        resposta = self.client.post(reverse('fidelidade:novo_evento'), self.payload(empresa_id=self.outra.pk))
        self.assertEqual(resposta.status_code, 302)
        evento = EventoFidelidade.objects.get()
        self.assertEqual(evento.empresa_id, self.empresa.pk)
        self.assertEqual(evento.efeitos.get().valor, Decimal('1.0025'))
        self.assertContains(self.client.get(reverse('fidelidade:eventos')), 'Campanha')
        self.assertContains(self.client.get(reverse('empresas:area')), reverse('fidelidade:eventos'))
        resposta = self.client.post(reverse('fidelidade:cancelar_evento', args=[evento.pk]))
        self.assertEqual(resposta.status_code, 302)
        evento.refresh_from_db()
        self.assertEqual(evento.estado, 'CANCELADO')
        self.assertContains(self.client.get(reverse('fidelidade:eventos')), 'CANCELADO')

    def test_forms_filtram_lojas_e_rejeitam_ids_externos_e_tipos_nao_operacionais(self):
        self.login()
        url = reverse('fidelidade:novo_evento')
        form = self.client.get(url).context['form']
        self.assertEqual(set(form.fields['lojas'].queryset.values_list('pk', flat=True)), {self.loja.pk, self.segunda.pk})
        self.assertNotIn('tipo', form.fields)
        for dados in ({'escopo': 'LOJAS', 'lojas': [self.externa.pk]},
                      {'escopo': 'LOJAS', 'lojas': []}, {'escopo': 'EMPRESA', 'lojas': [self.loja.pk]},
                      {'multiplicador': '0'}, {'multiplicador': '0.00001'}):
            resposta = self.client.post(url, self.payload(**dados))
            self.assertEqual(resposta.status_code, 200)
            self.assertTrue(resposta.context['form'].errors)
            self.assertFalse(EventoFidelidade.objects.exists())
        resposta = self.client.post(url, self.payload(escopo='LOJAS', lojas=[self.loja.pk, self.segunda.pk]))
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(EventoFidelidade.objects.get().lojas_selecionadas.count(), 2)
        # Mesmo período: conflito de domínio aparece como erro de formulário.
        resposta = self.client.post(url, self.payload())
        self.assertTrue(resposta.context['form'].non_field_errors())
        self.assertEqual(EventoFidelidade.objects.count(), 1)

    def test_gestor_inativo_anonimo_tenant_e_csrf(self):
        evento = self.evento()
        externo = self.evento(request=self.request(self.outro_membro), nome='Externo')
        listar, criar = reverse('fidelidade:eventos'), reverse('fidelidade:novo_evento')
        cancelar = reverse('fidelidade:cancelar_evento', args=[evento.pk])
        self.assertEqual(self.client.get(listar).status_code, 302)
        self.login()
        self.assertNotContains(self.client.get(listar), 'Externo')
        self.assertEqual(self.client.post(reverse('fidelidade:cancelar_evento', args=[externo.pk])).status_code, 403)
        self.assertEqual(self.client.get(cancelar).status_code, 405)
        navegador = Client(enforce_csrf_checks=True)
        self.login(navegador)
        self.assertEqual(navegador.post(cancelar).status_code, 403)
        self.assertEqual(navegador.post(criar, self.payload()).status_code, 403)
        navegador.get(listar)
        resposta = navegador.post(cancelar, {'csrfmiddlewaretoken': navegador.cookies['csrftoken'].value})
        self.assertEqual(resposta.status_code, 302)
        for papel, ativo in (('GESTOR', True), ('ADMINISTRADOR', False)):
            self.membro.papel, self.membro.ativo = papel, ativo
            self.membro.save()
            self.login()
            self.assertEqual(self.client.get(listar).status_code, 403)
            self.assertEqual(self.client.post(criar, self.payload()).status_code, 403)
            self.assertEqual(self.client.post(cancelar).status_code, 403)


class EventoCompraHTTPTests(DadosEventos, TestCase):
    def enviar(self, **mudancas):
        return APIClient().post('/api/v1/compras/', dict({
            'loja_id': self.loja.pk, 'cliente_cpf': self.usuario.cpf,
            'identificador_externo': 'VENDA-000123', 'valor': '49.90', 'ocorrida_em': self.instante.isoformat(),
        }, **mudancas), format='json', HTTP_X_API_KEY=self.chave)

    def test_contrato_201_200_409_sem_campos_internos_e_sem_recalcular(self):
        evento = self.evento()
        ConfiguracaoFidelidadeEmpresa.objects.create(empresa=self.empresa, pontos_por_real=Decimal('1.25'))
        primeira = self.enviar()
        self.assertEqual(primeira.status_code, 201)
        self.assertEqual(primeira.json()['fidelidade'], {'pontos_base': '62.3750', 'pontos_concedidos': '124.7500',
                                                      'expira_em': '2027-09-23T10:30:00-03:00'})
        cancelar_evento(self.request(), evento.pk)
        with patch('apps.fidelidade.services.resolver_efeito_evento', side_effect=AssertionError('Retry não resolve')):
            retry = self.enviar()
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json(), primeira.json())
        self.assertEqual(self.enviar(valor='50.00').status_code, 409)
        self.assertEqual(Compra.objects.count(), 1)
        self.assertEqual(LotePontos.objects.count(), 1)
        self.assertEqual(AplicacaoEfeitoEventoLote.objects.count(), 1)

    def test_resultado_nao_representavel_400_rollback(self):
        self.evento()
        ConfiguracaoFidelidadeEmpresa.objects.create(empresa=self.empresa, pontos_por_real=Decimal('9999999999.99'))
        resposta = self.enviar(valor='9999999999.99')
        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(resposta.json()['erro']['codigo'], 'requisicao_invalida')
        self.assertFalse(Compra.objects.exists())
        self.assertFalse(LotePontos.objects.exists())
        self.assertFalse(AplicacaoEfeitoEventoLote.objects.exists())

    def test_legado_null_nao_resolve_evento(self):
        self.evento()
        self.model(valor=Decimal('49.90')).save()
        with patch('apps.fidelidade.services.resolver_efeito_evento', side_effect=AssertionError('Sem backfill')):
            resposta = self.enviar()
        self.assertEqual(resposta.status_code, 200)
        self.assertIsNone(resposta.json()['fidelidade'])
        self.assertFalse(LotePontos.objects.exists())
        self.assertFalse(AplicacaoEfeitoEventoLote.objects.exists())


class EventoOpenAPITests(SimpleTestCase):
    def test_schema_preserva_paths_e_contrato_fidelidade(self):
        resposta = self.client.get('/api/schema/', HTTP_ACCEPT='application/vnd.oai.openapi+json')
        self.assertEqual(resposta.status_code, 200)
        schema = json.loads(resposta.content)
        self.assertEqual(set(schema['paths']), {'/api/v1/health/', '/api/v1/contexto/', '/api/v1/clientes/fidelidade/', '/api/v1/compras/simular/', '/api/v1/compras/', '/api/v1/resgates/'})
        post = schema['paths']['/api/v1/compras/']['post']
        self.assertEqual(post['security'], [{'X-API-Key': []}])
        self.assertTrue({'201', '200', '400', '409'} <= set(post['responses']))
        self.assertEqual(set(schema['components']['schemas']['FidelidadeCompra']['properties']),
                         {'pontos_base', 'pontos_concedidos', 'expira_em'})
