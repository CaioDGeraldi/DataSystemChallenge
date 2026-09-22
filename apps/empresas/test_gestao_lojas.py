from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import Client as Navegador, RequestFactory, TestCase
from django.urls import reverse

from apps.clientes.models import Cliente
from apps.usuarios.services import CONTEXTO_SESSAO

from .models import AcessoLoja, Empresa, Loja, MembroEmpresa
from .services import criar_loja_no_contexto


class GestaoLojasTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user("52998224725", "Fortaleza!9042")
        cls.empresa = Empresa.objects.create(nome="Empresa A", slug="empresa-a", cnpj="11222333000181")
        cls.outra = Empresa.objects.create(nome="Empresa B", slug="empresa-b", cnpj="11444777000161")
        cls.membro = MembroEmpresa.objects.create(usuario=cls.usuario, empresa=cls.empresa,
                                                 papel=MembroEmpresa.Papel.ADMINISTRADOR)
        cls.loja = Loja.objects.create(empresa=cls.empresa, nome="Centro", cidade="Franca")
        cls.loja_b = Loja.objects.create(empresa=cls.outra, nome="Loja B", cidade="Campinas")

    def setUp(self):
        self.client.force_login(self.usuario)
        sessao = self.client.session
        sessao[CONTEXTO_SESSAO] = self.contexto()
        sessao.save()

    def contexto(self):
        return {"tipo_contexto": "gestao", "empresa_id": self.empresa.pk, "vinculo_id": self.membro.pk}

    def criar(self, **extras):
        return self.client.post(reverse("empresas:criar_loja"), dict({"nome": "Shopping", "cidade": "Franca"}, **extras))

    def test_admin_cria_loja_adicional_no_tenant_ativo(self):
        self.assertRedirects(self.criar(), reverse("empresas:area"))
        nova = Loja.objects.get(nome="Shopping")
        self.assertEqual(nova.empresa_id, self.empresa.pk)
        self.assertEqual(nova.cidade, "Franca")
        self.assertFalse(AcessoLoja.objects.exists())

    def test_empresa_e_membro_adulterados_no_post_nao_trocam_tenant(self):
        outro_vinculo = MembroEmpresa.objects.create(usuario=self.usuario, empresa=self.outra,
                                                     papel=MembroEmpresa.Papel.ADMINISTRADOR)
        self.assertEqual(self.criar(empresa_id=self.outra.pk, membro_id=outro_vinculo.pk).status_code, 302)
        self.assertEqual(Loja.objects.get(nome="Shopping").empresa_id, self.empresa.pk)
        self.assertEqual(self.outra.lojas.count(), 1)
        self.assertEqual(self.client.session[CONTEXTO_SESSAO], self.contexto())

    def test_contexto_com_empresa_adulterada_e_rejeitado(self):
        sessao = self.client.session
        sessao[CONTEXTO_SESSAO] = dict(self.contexto(), empresa_id=self.outra.pk)
        sessao.save()
        self.assertEqual(self.criar().status_code, 403)
        self.assertEqual(Loja.objects.count(), 2)

    def test_admin_lista_todas_as_lojas_da_empresa_e_nenhuma_de_fora(self):
        nova = Loja.objects.create(empresa=self.empresa, nome="Nova", cidade="Franca")
        resposta = self.client.get(reverse("empresas:area"))
        self.assertCountEqual(resposta.context["lojas"], [self.loja, nova])
        self.assertContains(resposta, reverse("empresas:criar_loja"))
        self.assertFalse(AcessoLoja.objects.exists())

    def test_gestor_lista_apenas_lojas_atribuidas(self):
        self.membro.papel = MembroEmpresa.Papel.GESTOR
        self.membro.save()
        segunda = Loja.objects.create(empresa=self.empresa, nome="Segunda", cidade="Franca")
        Loja.objects.create(empresa=self.empresa, nome="Não atribuída", cidade="Franca")
        for loja in (self.loja, segunda):
            AcessoLoja.objects.create(membro=self.membro, loja=loja)
        resposta = self.client.get(reverse("empresas:area"))
        self.assertEqual(resposta.status_code, 200)
        self.assertCountEqual(resposta.context["lojas"], [self.loja, segunda])
        self.assertNotContains(resposta, reverse("empresas:criar_loja"))

    def test_gestor_sem_acesso_nao_recebe_lojas(self):
        self.membro.papel = MembroEmpresa.Papel.GESTOR
        self.membro.save()
        resposta = self.client.get(reverse("empresas:area"))
        self.assertEqual(list(resposta.context["lojas"]), [])

    def test_gestor_nao_cria_loja_por_get_post_ou_servico(self):
        self.membro.papel = MembroEmpresa.Papel.GESTOR
        self.membro.save()
        self.assertEqual(self.client.get(reverse("empresas:criar_loja")).status_code, 403)
        self.assertEqual(self.criar().status_code, 403)
        request = RequestFactory().post("/gestao/lojas/nova/")
        request.user = self.usuario
        request.session = {CONTEXTO_SESSAO: self.contexto()}
        with self.assertRaises(PermissionDenied):
            criar_loja_no_contexto(request, nome="Indevida", cidade="Franca")
        self.assertEqual(Loja.objects.count(), 2)

    def test_desativacao_apos_login_revoga_criacao_e_listagem(self):
        self.membro.ativo = False
        self.membro.save()
        self.assertEqual(self.criar().status_code, 403)
        self.assertEqual(self.client.get(reverse("empresas:area")).status_code, 403)
        self.assertEqual(Loja.objects.count(), 2)

    def test_contexto_cliente_nao_autoriza_criacao(self):
        cliente = Cliente.objects.create(usuario=self.usuario, empresa=self.empresa)
        sessao = self.client.session
        sessao[CONTEXTO_SESSAO] = {"tipo_contexto": "cliente", "empresa_id": self.empresa.pk, "vinculo_id": cliente.pk}
        sessao.save()
        self.assertEqual(self.criar().status_code, 403)

    def test_vinculo_removido_nao_permanece_autorizado_pela_sessao(self):
        self.membro.delete()
        self.assertEqual(self.criar().status_code, 403)
        self.assertNotIn(CONTEXTO_SESSAO, self.client.session)
        self.assertEqual(self.client.get(reverse("empresas:area")).status_code, 403)
        self.assertEqual(Loja.objects.count(), 2)

    def test_nao_autenticado_nao_cria_loja(self):
        self.client.logout()
        resposta = self.criar()
        self.assertEqual(resposta.status_code, 302)
        self.assertTrue(resposta.url.startswith(reverse("usuarios:login")))
        self.assertEqual(Loja.objects.count(), 2)

    def test_nome_e_cidade_obrigatorios(self):
        for dados in ({"nome": ""}, {"cidade": ""}):
            with self.subTest(dados=dados):
                resposta = self.criar(**dados)
                self.assertTrue(resposta.context["form"].errors)
        self.assertEqual(Loja.objects.count(), 2)

    def test_criacao_de_loja_exige_csrf(self):
        navegador = Navegador(enforce_csrf_checks=True)
        navegador.force_login(self.usuario)
        sessao = navegador.session
        sessao[CONTEXTO_SESSAO] = self.contexto()
        sessao.save()
        self.assertEqual(navegador.post(reverse("empresas:criar_loja"), {"nome": "Nova", "cidade": "Franca"}).status_code, 403)
        self.assertEqual(Loja.objects.count(), 2)
