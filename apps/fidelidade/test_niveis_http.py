from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from apps.usuarios.services import CONTEXTO_SESSAO

from .models import NivelFidelidade
from .test_niveis import DadosNiveis


class GestaoNivelTests(DadosNiveis, TestCase):
    def login(self, client=None):
        client = client or self.client
        client.force_login(self.usuario)
        sessao = client.session
        sessao[CONTEXTO_SESSAO] = self.request().session[CONTEXTO_SESSAO]
        sessao.save()

    def test_admin_cria_edita_lista_e_exclui_no_tenant_da_sessao(self):
        self.login()
        resposta = self.client.post(
            reverse('fidelidade:novo_nivel'),
            {
                'nome': '  Inicial  ',
                'pontos_minimos': '0.0000',
                'empresa_id': self.outra.pk,
            },
        )
        self.assertRedirects(resposta, reverse('fidelidade:niveis'))
        zero = NivelFidelidade.objects.get()
        self.assertEqual(
            (zero.nome, zero.empresa_id),
            ('Inicial', self.empresa.pk),
        )
        alto = self.nivel('Alto', '1000')
        medio = self.nivel('Médio', '500')
        resposta = self.client.get(reverse('fidelidade:niveis'))
        self.assertEqual(list(resposta.context['niveis']), [zero, medio, alto])
        self.assertContains(
            self.client.get(reverse('empresas:area')),
            reverse('fidelidade:niveis'),
        )
        editar = reverse('fidelidade:editar_nivel', args=[medio.pk])
        self.assertEqual(
            self.client.get(editar).context['form'].initial['nome'],
            'Médio',
        )
        resposta = self.client.post(
            editar,
            {
                'nome': 'Atualizado',
                'pontos_minimos': '750.1250',
                'empresa': self.outra.pk,
            },
        )
        self.assertEqual(resposta.status_code, 302)
        medio.refresh_from_db()
        self.assertEqual(
            (medio.nome, medio.pontos_minimos, medio.empresa_id),
            ('Atualizado', Decimal('750.1250'), self.empresa.pk),
        )
        self.assertEqual(
            self.client.post(reverse('fidelidade:excluir_nivel', args=[medio.pk])).status_code,
            302,
        )
        self.assertFalse(NivelFidelidade.objects.filter(pk=medio.pk).exists())

    def test_beneficios_editaveis_independentes_e_percentuais_invalidos(self):
        self.login()
        zero = self.nivel()
        url = reverse('fidelidade:editar_nivel', args=[zero.pk])
        dados = {
            'nome': zero.nome,
            'pontos_minimos': '0',
            'bonus_pontos_percentual': '20.1250',
            'desconto_percentual': '5.0000',
        }
        self.assertEqual(self.client.post(url, dados).status_code, 302)
        zero.refresh_from_db()
        self.assertEqual(zero.bonus_pontos_percentual, Decimal('20.1250'))
        self.assertEqual(zero.desconto_percentual, Decimal('5'))
        self.assertEqual(
            self.client.get(url).context['form'].initial['desconto_percentual'],
            Decimal('5'),
        )
        for campo in ('bonus_pontos_percentual', 'desconto_percentual'):
            resposta = self.client.post(url, dict(dados, **{campo: '100.0001'}))
            self.assertIn(campo, resposta.context['form'].errors)
        zero.refresh_from_db()
        self.assertEqual(zero.bonus_pontos_percentual, Decimal('20.1250'))

    def test_form_erros_de_campos_e_invariantes_sem_persistencia_parcial(self):
        self.login()
        criar = reverse('fidelidade:novo_nivel')
        self.assertEqual(
            set(self.client.get(criar).context['form'].fields),
            {
                'nome',
                'pontos_minimos',
                'bonus_pontos_percentual',
                'desconto_percentual',
            },
        )
        for dados in (
            {'nome': '', 'pontos_minimos': '0'},
            {'nome': 'a' * 256, 'pontos_minimos': '0'},
            {'nome': 'X', 'pontos_minimos': '-1'},
            {'nome': 'X', 'pontos_minimos': '.00001'},
            {'nome': 'X', 'pontos_minimos': 'NaN'},
            {'nome': 'X', 'pontos_minimos': '100000000000000000000'},
            {'nome': 'Sem zero', 'pontos_minimos': '1'},
        ):
            resposta = self.client.post(criar, dados)
            self.assertEqual(resposta.status_code, 200)
            self.assertTrue(resposta.context['form'].errors)
        self.assertFalse(NivelFidelidade.objects.exists())
        zero, meio, _ = self.faixas()
        for id_nivel, pontos in ((zero.pk, '1'), (meio.pk, '5000')):
            resposta = self.client.post(
                reverse('fidelidade:editar_nivel', args=[id_nivel]),
                {'nome': 'Inválido', 'pontos_minimos': pontos},
            )
            self.assertTrue(resposta.context['form'].non_field_errors())
        resposta = self.client.post(
            reverse('fidelidade:excluir_nivel', args=[zero.pk]),
            follow=True,
        )
        self.assertContains(resposta, 'Mantenha um nível em zero')
        self.assertEqual(NivelFidelidade.objects.count(), 3)

    def test_cross_tenant_inexistente_e_listagem_sem_vazamento(self):
        self.login()
        self.nivel('Local')
        externo = self.nivel('SEGREDO-EXTERNO', request=self.request(self.outro_membro))
        self.assertNotContains(
            self.client.get(reverse('fidelidade:niveis')),
            'SEGREDO-EXTERNO',
        )
        for id_nivel in (externo.pk, 999999):
            editar = reverse('fidelidade:editar_nivel', args=[id_nivel])
            self.assertEqual(self.client.get(editar).status_code, 403)
            self.assertEqual(
                self.client.post(editar, {'nome': 'X', 'pontos_minimos': '0'}).status_code,
                403,
            )
            self.assertEqual(
                self.client.post(reverse('fidelidade:excluir_nivel', args=[id_nivel])).status_code,
                403,
            )
        externo.refresh_from_db()
        self.assertEqual(externo.nome, 'SEGREDO-EXTERNO')

    def test_anonimo_gestor_e_inativo_nao_listam_nem_alteram(self):
        zero = self.nivel()
        listar, criar = reverse('fidelidade:niveis'), reverse('fidelidade:novo_nivel')
        editar = reverse('fidelidade:editar_nivel', args=[zero.pk])
        excluir = reverse('fidelidade:excluir_nivel', args=[zero.pk])
        for rota in (listar, criar, editar):
            self.assertEqual(self.client.get(rota).status_code, 302)
        for papel, ativo in (('GESTOR', True), ('ADMINISTRADOR', False)):
            self.membro.papel, self.membro.ativo = papel, ativo
            self.membro.save()
            self.login()
            for rota in (listar, criar, editar):
                self.assertEqual(self.client.get(rota).status_code, 403)
            for rota in (criar, editar, excluir):
                self.assertEqual(
                    self.client.post(rota, {'nome': 'X', 'pontos_minimos': '0'}).status_code,
                    403,
                )
        self.assertEqual(NivelFidelidade.objects.get().nome, 'Inicial')

    def test_csrf_e_metodos_exclusao_somente_post(self):
        zero = self.nivel()
        self.login()
        excluir = reverse('fidelidade:excluir_nivel', args=[zero.pk])
        self.assertEqual(self.client.get(excluir).status_code, 405)
        navegador = Client(enforce_csrf_checks=True)
        self.login(navegador)
        for rota in (
            reverse('fidelidade:novo_nivel'),
            reverse('fidelidade:editar_nivel', args=[zero.pk]),
            excluir,
        ):
            self.assertEqual(
                navegador.post(rota, {'nome': 'X', 'pontos_minimos': '0'}).status_code,
                403,
            )
        navegador.get(reverse('fidelidade:niveis'))
        resposta = navegador.post(
            excluir,
            {'csrfmiddlewaretoken': navegador.cookies['csrftoken'].value},
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertFalse(NivelFidelidade.objects.exists())

    def test_sem_api_publica_nem_classificacao_exposta_na_compra(self):
        resposta = self.client.get(
            '/api/schema/',
            HTTP_ACCEPT='application/vnd.oai.openapi+json',
        )
        schema = resposta.json()
        self.assertEqual(
            set(schema['paths']),
            {
                '/api/v1/health/',
                '/api/v1/contexto/',
                '/api/v1/clientes/fidelidade/',
                '/api/v1/compras/simular/',
                '/api/v1/compras/',
                '/api/v1/resgates/simular/', '/api/v1/resgates/',
            },
        )
        self.assertNotIn('NivelFidelidade', schema['components']['schemas'])
