from django.contrib.auth import get_user_model
from django.test import Client as Navegador, TestCase
from django.urls import reverse

from apps.clientes.models import Cliente
from apps.empresas.models import Empresa, MembroEmpresa

from .services import CONTEXTO_SESSAO, resolver_contextos


SENHA = "Fortaleza!9042"


class ContextoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user("52998224725", SENHA, first_name="Ana", last_name="Silva")
        cls.outro = get_user_model().objects.create_user("11144477735", SENHA)
        cls.empresa = Empresa.objects.create(nome="Empresa A", slug="empresa-a", cnpj="11222333000181")
        cls.empresa_b = Empresa.objects.create(nome="Empresa B", slug="empresa-b", cnpj="11444777000161")

    def criar_cliente(self, empresa=None, usuario=None):
        return Cliente.objects.create(usuario=usuario or self.usuario, empresa=empresa or self.empresa)

    def criar_membro(self, empresa=None, ativo=True, papel=MembroEmpresa.Papel.GESTOR):
        return MembroEmpresa.objects.create(usuario=self.usuario, empresa=empresa or self.empresa, papel=papel, ativo=ativo)

    def entrar(self, **dados):
        return self.client.post(reverse("usuarios:login"), dict({"cpf": self.usuario.cpf, "senha": SENHA}, **dados))

    def test_login_canonico_e_mascarado_ativa_contexto_unico(self):
        cliente = self.criar_cliente()
        for cpf in (self.usuario.cpf, "529.982.247-25"):
            with self.subTest(cpf=cpf):
                self.assertRedirects(self.entrar(cpf=cpf), reverse("clientes:area"))
                self.assertEqual(self.client.session[CONTEXTO_SESSAO], {
                    "tipo_contexto": "cliente", "empresa_id": self.empresa.pk, "vinculo_id": cliente.pk
                })
                self.client.logout()

    def test_login_senha_errada_e_cpf_malformado(self):
        self.criar_cliente()
        for dados in ({"senha": "errada"}, {"cpf": "abc"}, {"cpf": "529/982/247-25"}):
            with self.subTest(dados=dados):
                resposta = self.entrar(**dados)
                self.assertEqual(resposta.status_code, 200)
                self.assertContains(resposta, "CPF ou senha inválidos")
                self.assertNotIn("_auth_user_id", self.client.session)

    def test_usuario_inativo_nao_autentica(self):
        self.criar_cliente()
        self.usuario.is_active = False
        self.usuario.save()
        self.assertTrue(self.entrar().context["form"].errors)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_zero_contextos_e_negacao_de_autorizacao(self):
        resposta = self.entrar()
        self.assertContains(resposta, "Acesso não autorizado", status_code=403)
        self.assertNotIn(CONTEXTO_SESSAO, self.client.session)

    def test_resolve_vinculos_distintos_de_ambas_empresas(self):
        ca = self.criar_cliente()
        cb = self.criar_cliente(self.empresa_b)
        ma = self.criar_membro(papel=MembroEmpresa.Papel.ADMINISTRADOR)
        mb = self.criar_membro(self.empresa_b)
        self.criar_cliente(usuario=self.outro)
        contextos = resolver_contextos(self.usuario)
        self.assertCountEqual([(c["tipo_contexto"], c["empresa_id"], c["vinculo_id"]) for c in contextos], [
            ("cliente", self.empresa.pk, ca.pk), ("cliente", self.empresa_b.pk, cb.pk),
            ("gestao", self.empresa.pk, ma.pk), ("gestao", self.empresa_b.pk, mb.pk)
        ])
        mb.ativo = False
        mb.save()
        self.assertEqual(len(resolver_contextos(self.usuario)), 3)

    def test_membro_inativo_nao_gera_contexto(self):
        self.criar_membro(ativo=False)
        self.assertEqual(resolver_contextos(self.usuario), [])
        self.assertEqual(self.entrar().status_code, 403)

    def test_multiplos_contextos_exigem_escolha_e_aceitam_cada_tipo(self):
        cliente = self.criar_cliente()
        membro = self.criar_membro()
        for tipo, vinculo, destino in (("cliente", cliente, "clientes:area"), ("gestao", membro, "empresas:area")):
            with self.subTest(tipo=tipo):
                self.assertRedirects(self.entrar(), reverse("usuarios:selecionar_contexto"))
                self.assertNotIn(CONTEXTO_SESSAO, self.client.session)
                self.assertEqual(self.client.get(reverse(destino)).status_code, 403)
                resposta = self.client.post(reverse("usuarios:selecionar_contexto"), {"contexto": f"{tipo}:{vinculo.pk}"})
                self.assertRedirects(resposta, reverse(destino))
                self.client.logout()

    def test_selecao_em_empresa_diferente(self):
        self.criar_cliente()
        cliente_b = self.criar_cliente(self.empresa_b)
        self.entrar()
        self.client.post(reverse("usuarios:selecionar_contexto"), {"contexto": f"cliente:{cliente_b.pk}"})
        self.assertEqual(self.client.session[CONTEXTO_SESSAO]["empresa_id"], self.empresa_b.pk)
        self.assertContains(self.client.get(reverse("clientes:area")), "Empresa B")

    def test_nao_seleciona_contexto_de_outro_usuario_ou_fabricado(self):
        self.criar_cliente()
        self.criar_membro()
        alheio = self.criar_cliente(usuario=self.outro)
        self.entrar()
        for chave in (f"cliente:{alheio.pk}", "gestao:999999", "administrador:1", "abc"):
            with self.subTest(chave=chave):
                resposta = self.client.post(reverse("usuarios:selecionar_contexto"), {"contexto": chave})
                self.assertTrue(resposta.context["form"].errors)
                self.assertNotIn(CONTEXTO_SESSAO, self.client.session)

    def test_escolha_revalida_membro_desativado(self):
        self.criar_cliente()
        membro = self.criar_membro()
        self.entrar()
        membro.ativo = False
        membro.save()
        resposta = self.client.post(reverse("usuarios:selecionar_contexto"), {"contexto": f"gestao:{membro.pk}"})
        self.assertTrue(resposta.context["form"].errors)
        self.assertNotIn(CONTEXTO_SESSAO, self.client.session)

    def test_areas_rejeitam_tipo_incompativel(self):
        cliente = self.criar_cliente()
        self.entrar()
        self.assertEqual(self.client.get(reverse("empresas:area")).status_code, 403)
        self.assertEqual(self.client.get(reverse("clientes:area")).status_code, 200)
        self.client.logout()
        cliente.delete()
        self.criar_membro()
        self.entrar()
        self.assertEqual(self.client.get(reverse("clientes:area")).status_code, 403)
        self.assertEqual(self.client.get(reverse("empresas:area")).status_code, 200)

    def test_ambos_papeis_entram_em_gestao_sem_copiar_papel_ou_lojas(self):
        membro = self.criar_membro()
        for papel in MembroEmpresa.Papel.values:
            with self.subTest(papel=papel):
                membro.papel = papel
                membro.save()
                self.assertRedirects(self.entrar(), reverse("empresas:area"))
                self.assertEqual(self.client.session[CONTEXTO_SESSAO], {
                    "tipo_contexto": "gestao", "empresa_id": self.empresa.pk, "vinculo_id": membro.pk
                })
                self.client.logout()

    def test_membro_desativado_apos_login_perde_acesso(self):
        membro = self.criar_membro()
        self.entrar()
        membro.ativo = False
        membro.save()
        self.assertEqual(self.client.get(reverse("empresas:area")).status_code, 403)
        self.assertNotIn(CONTEXTO_SESSAO, self.client.session)

    def test_usuario_desativado_apos_login_perde_acesso(self):
        self.criar_cliente()
        self.entrar()
        self.usuario.is_active = False
        self.usuario.save()
        resposta = self.client.get(reverse("clientes:area"))
        self.assertEqual(resposta.status_code, 302)
        self.assertTrue(resposta.url.startswith(reverse("usuarios:login")))

    def test_vinculos_removidos_nao_autorizam_por_sessao(self):
        for tipo in ("cliente", "gestao"):
            with self.subTest(tipo=tipo):
                vinculo = self.criar_cliente() if tipo == "cliente" else self.criar_membro()
                self.entrar()
                vinculo.delete()
                destino = "clientes:area" if tipo == "cliente" else "empresas:area"
                self.assertEqual(self.client.get(reverse(destino)).status_code, 403)
                self.assertNotIn(CONTEXTO_SESSAO, self.client.session)
                self.client.logout()

    def test_sessao_invalida_nao_autoriza(self):
        cliente = self.criar_cliente()
        alheio = self.criar_cliente(usuario=self.outro)
        self.client.force_login(self.usuario)
        for contexto in (None, {}, "abc", {"tipo_contexto": "cliente", "empresa_id": self.empresa_b.pk, "vinculo_id": cliente.pk},
                         {"tipo_contexto": "cliente", "empresa_id": self.empresa.pk, "vinculo_id": alheio.pk}):
            with self.subTest(contexto=contexto):
                sessao = self.client.session
                sessao[CONTEXTO_SESSAO] = contexto
                sessao.save()
                self.assertEqual(self.client.get(reverse("clientes:area")).status_code, 403)

    def test_nao_autenticado_e_bloqueado(self):
        for rota in ("clientes:area", "empresas:area", "usuarios:selecionar_contexto"):
            with self.subTest(rota=rota):
                resposta = self.client.get(reverse(rota))
                self.assertEqual(resposta.status_code, 302)
                self.assertTrue(resposta.url.startswith(reverse("usuarios:login")))

    def test_sessao_ativa_nao_permite_troca_de_contexto(self):
        cliente = self.criar_cliente()
        membro = self.criar_membro()
        self.entrar()
        self.client.post(reverse("usuarios:selecionar_contexto"), {"contexto": f"cliente:{cliente.pk}"})
        resposta = self.client.post(reverse("usuarios:selecionar_contexto"), {"contexto": f"gestao:{membro.pk}"})
        self.assertRedirects(resposta, reverse("clientes:area"))
        self.assertEqual(self.client.session[CONTEXTO_SESSAO]["tipo_contexto"], "cliente")

    def test_logout_post_limpa_autenticacao_e_contexto(self):
        self.criar_cliente()
        self.entrar()
        self.assertEqual(self.client.get(reverse("usuarios:logout")).status_code, 405)
        self.assertRedirects(self.client.post(reverse("usuarios:logout")), reverse("usuarios:login"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertNotIn(CONTEXTO_SESSAO, self.client.session)

    def test_csrf_exigido_nos_posts_e_logout_com_token_funciona(self):
        self.criar_cliente()
        navegador = Navegador(enforce_csrf_checks=True)
        navegador.get(reverse("usuarios:login"))
        for rota in (reverse("usuarios:login"), reverse("clientes:cadastro", args=[self.empresa.slug])):
            self.assertEqual(navegador.post(rota, {}).status_code, 403)
        token = navegador.cookies["csrftoken"].value
        resposta = navegador.post(reverse("usuarios:login"), {"cpf": self.usuario.cpf, "senha": SENHA, "csrfmiddlewaretoken": token})
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(navegador.post(reverse("usuarios:selecionar_contexto"), {}).status_code, 403)
        self.assertEqual(navegador.post(reverse("usuarios:logout"), {}).status_code, 403)
        resposta = navegador.post(reverse("usuarios:logout"), {"csrfmiddlewaretoken": navegador.cookies["csrftoken"].value})
        self.assertEqual(resposta.status_code, 302)
        self.assertNotIn("_auth_user_id", navegador.session)
