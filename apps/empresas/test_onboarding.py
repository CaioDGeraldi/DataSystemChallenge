from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, local
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connections
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import Client as Navegador, RequestFactory, TestCase, TransactionTestCase
from django.urls import reverse

from apps.clientes.models import Cliente
from apps.usuarios.services import CONTEXTO_SESSAO

from .models import AcessoLoja, Empresa, Loja, MembroEmpresa
from .services import concluir_onboarding, gerar_slug_disponivel


SENHA = "Fortaleza!9042"


class OnboardingTests(TestCase):
    def dados(self, **alteracoes):
        return dict({
            "cpf": "529.982.247-25", "first_name": "Ana", "last_name": "Silva",
            "senha": SENHA, "confirmacao": SENHA, "nome_empresa": "Loja do Caio",
            "cnpj": "11.222.333/0001-81", "nome_loja": "Centro", "cidade_loja": "Franca",
        }, **alteracoes)

    def concluir(self, **alteracoes):
        return self.client.post(reverse("empresas:onboarding"), self.dados(**alteracoes))

    def usuario_existente(self, **extra):
        return get_user_model().objects.create_user(
            "52998224725", SENHA, first_name="Original", last_name="Pessoa", **extra
        )

    def assert_sem_dominio(self):
        self.assertFalse(Empresa.objects.exists())
        self.assertFalse(Loja.objects.exists())
        self.assertFalse(MembroEmpresa.objects.exists())

    def test_nova_identidade_onboarding_completo_e_contexto_minimo(self):
        resposta = self.concluir()
        self.assertRedirects(resposta, reverse("empresas:area"))
        usuario = get_user_model().objects.get()
        empresa = Empresa.objects.get()
        loja = Loja.objects.get()
        membro = MembroEmpresa.objects.get()
        self.assertEqual(usuario.cpf, "52998224725")
        self.assertEqual((usuario.first_name, usuario.last_name), ("Ana", "Silva"))
        self.assertTrue(usuario.check_password(SENHA))
        self.assertNotEqual(usuario.password, SENHA)
        self.assertEqual((empresa.cnpj, empresa.slug), ("11222333000181", "loja-do-caio"))
        self.assertEqual((loja.empresa_id, loja.nome, loja.cidade), (empresa.pk, "Centro", "Franca"))
        self.assertEqual((membro.usuario_id, membro.empresa_id), (usuario.pk, empresa.pk))
        self.assertEqual(membro.papel, MembroEmpresa.Papel.ADMINISTRADOR)
        self.assertTrue(membro.ativo)
        self.assertFalse(AcessoLoja.objects.exists())
        self.assertFalse(Cliente.objects.exists())
        self.assertEqual(self.client.session["_auth_user_id"], str(usuario.pk))
        self.assertEqual(self.client.session[CONTEXTO_SESSAO], {
            "tipo_contexto": "gestao", "empresa_id": empresa.pk, "vinculo_id": membro.pk,
        })

    def test_formulario_publico_nao_solicita_slug(self):
        resposta = self.client.get(reverse("empresas:onboarding"))
        self.assertEqual(resposta.status_code, 200)
        self.assertNotIn("slug", resposta.context["form"].fields)
        self.assertIn("cpf", resposta.context["form"].fields)

    def test_nova_identidade_exige_nomes_senhas_e_primeira_loja(self):
        for dados in (
            {"first_name": ""}, {"last_name": ""}, {"senha": ""}, {"confirmacao": "diferente"},
            {"senha": "123", "confirmacao": "123"}, {"cpf": "abc"}, {"cnpj": "abc"},
            {"nome_empresa": ""}, {"nome_loja": ""}, {"cidade_loja": ""},
        ):
            with self.subTest(dados=dados):
                resposta = self.concluir(**dados)
                self.assertEqual(resposta.status_code, 200)
                self.assertTrue(resposta.context["form"].errors)
                self.assertFalse(get_user_model().objects.exists())
                self.assert_sem_dominio()

    def test_aplica_password_validators_configurados(self):
        with self.settings(AUTH_PASSWORD_VALIDATORS=[{
            "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
            "OPTIONS": {"min_length": 100},
        }]):
            self.assertTrue(self.concluir().context["form"].errors)
        self.assertFalse(get_user_model().objects.exists())
        self.assert_sem_dominio()

    def test_identidade_existente_preserva_dados_e_senha(self):
        usuario = self.usuario_existente()
        originais = (usuario.cpf, usuario.first_name, usuario.last_name, usuario.password)
        with self.settings(AUTH_PASSWORD_VALIDATORS=[{
            "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
            "OPTIONS": {"min_length": 100},
        }]):
            self.assertEqual(self.concluir(first_name="Outro", last_name="Nome").status_code, 302)
        usuario.refresh_from_db()
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual((usuario.cpf, usuario.first_name, usuario.last_name, usuario.password), originais)
        self.assertEqual(MembroEmpresa.objects.get().usuario_id, usuario.pk)

    def test_identidade_existente_nao_exige_nomes(self):
        self.usuario_existente()
        self.assertEqual(self.concluir(first_name="", last_name="").status_code, 302)

    def test_senha_incorreta_nao_cria_dominio(self):
        self.usuario_existente()
        self.assertTrue(self.concluir(senha="Errada!9042", confirmacao="Errada!9042").context["form"].errors)
        self.assert_sem_dominio()

    def test_usuario_inativo_nao_cria_dominio(self):
        self.usuario_existente(is_active=False)
        self.assertTrue(self.concluir().context["form"].errors)
        self.assert_sem_dominio()

    def test_autenticado_ignora_identidade_adulterada_e_nao_exige_senha(self):
        dono = self.usuario_existente()
        outro = get_user_model().objects.create_user("11144477735", SENHA)
        self.client.force_login(dono)
        resposta = self.client.get(reverse("empresas:onboarding"))
        self.assertNotIn("cpf", resposta.context["form"].fields)
        self.assertNotIn("senha", resposta.context["form"].fields)
        self.assertEqual(self.concluir(usuario_id=outro.pk, cpf=outro.cpf, senha="", confirmacao="").status_code, 302)
        self.assertEqual(MembroEmpresa.objects.get().usuario_id, dono.pk)
        self.assertEqual(get_user_model().objects.count(), 2)

    def test_cliente_autenticado_pode_substituir_contexto_ao_criar_empresa(self):
        usuario = self.usuario_existente()
        antiga = Empresa.objects.create(nome="Empresa anterior", slug="anterior", cnpj="11444777000161")
        cliente = Cliente.objects.create(usuario=usuario, empresa=antiga)
        self.client.force_login(usuario)
        sessao = self.client.session
        sessao[CONTEXTO_SESSAO] = {"tipo_contexto": "cliente", "empresa_id": antiga.pk, "vinculo_id": cliente.pk}
        sessao.save()
        self.assertRedirects(self.concluir(), reverse("empresas:area"))
        novo = MembroEmpresa.objects.get()
        self.assertEqual(self.client.session[CONTEXTO_SESSAO], {
            "tipo_contexto": "gestao", "empresa_id": novo.empresa_id, "vinculo_id": novo.pk,
        })
        self.assertTrue(Cliente.objects.filter(pk=cliente.pk).exists())
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_membro_de_outra_empresa_pode_administrar_nova_empresa(self):
        usuario = self.usuario_existente()
        antiga = Empresa.objects.create(nome="Empresa anterior", slug="anterior", cnpj="11444777000161")
        anterior = MembroEmpresa.objects.create(usuario=usuario, empresa=antiga, papel=MembroEmpresa.Papel.GESTOR)
        self.client.force_login(usuario)
        sessao = self.client.session
        sessao[CONTEXTO_SESSAO] = {"tipo_contexto": "gestao", "empresa_id": antiga.pk, "vinculo_id": anterior.pk}
        sessao.save()
        self.assertEqual(self.concluir().status_code, 302)
        self.assertEqual(usuario.membros_empresas.count(), 2)
        self.assertNotEqual(self.client.session[CONTEXTO_SESSAO]["empresa_id"], antiga.pk)
        anterior.refresh_from_db()
        self.assertEqual(anterior.papel, MembroEmpresa.Papel.GESTOR)

    def test_rollback_de_nova_identidade_em_cada_etapa(self):
        for alvo in ("Empresa.objects.create", "Loja.save", "MembroEmpresa.objects.create"):
            with self.subTest(alvo=alvo):
                with patch(f"apps.empresas.services.{alvo}", side_effect=IntegrityError("falha simulada")):
                    with self.assertRaises(IntegrityError):
                        self.concluir()
                self.assertFalse(get_user_model().objects.exists())
                self.assert_sem_dominio()
                self.assertNotIn("_auth_user_id", self.client.session)
                self.assertNotIn(CONTEXTO_SESSAO, self.client.session)

    def test_falha_preserva_identidade_e_contexto_anteriores(self):
        usuario = self.usuario_existente()
        antiga = Empresa.objects.create(nome="Empresa anterior", slug="anterior", cnpj="11444777000161")
        cliente = Cliente.objects.create(usuario=usuario, empresa=antiga)
        contexto = {"tipo_contexto": "cliente", "empresa_id": antiga.pk, "vinculo_id": cliente.pk}
        self.client.force_login(usuario)
        sessao = self.client.session
        sessao[CONTEXTO_SESSAO] = contexto
        sessao.save()
        with patch("apps.empresas.services.Loja.save", side_effect=IntegrityError("falha simulada")):
            with self.assertRaises(IntegrityError):
                self.concluir()
        self.assertEqual(Empresa.objects.count(), 1)
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertFalse(Loja.objects.exists())
        self.assertFalse(MembroEmpresa.objects.exists())
        self.assertEqual(self.client.session[CONTEXTO_SESSAO], contexto)

    def test_cnpj_duplicado_falha_sem_residuo(self):
        antiga = Empresa.objects.create(nome="Empresa anterior", slug="anterior", cnpj="11222333000181")
        self.assertTrue(self.concluir().context["form"].errors)
        self.assertEqual(list(Empresa.objects.values_list("pk", flat=True)), [antiga.pk])
        self.assertFalse(get_user_model().objects.exists())
        self.assertFalse(Loja.objects.exists())
        self.assertFalse(MembroEmpresa.objects.exists())

    def test_nomes_iguais_geram_slugs_distintos_e_preservam_empresas(self):
        self.concluir()
        primeira = Empresa.objects.get()
        self.concluir(cnpj="11.444.777/0001-61", slug="adulterado")
        self.assertCountEqual(Empresa.objects.values_list("slug", flat=True), ["loja-do-caio", "loja-do-caio-2"])
        self.assertEqual(MembroEmpresa.objects.filter(papel=MembroEmpresa.Papel.ADMINISTRADOR).count(), 2)
        primeira.refresh_from_db()
        self.assertEqual(primeira.cnpj, "11222333000181")
        primeira.slug = "outro"
        with self.assertRaises(ValidationError):
            primeira.save()

    def test_slug_existente_nao_e_sobrescrito(self):
        antiga = Empresa.objects.create(nome="Existente", slug="loja-do-caio", cnpj="11444777000161")
        self.concluir()
        antiga.refresh_from_db()
        self.assertEqual(antiga.nome, "Existente")
        self.assertTrue(Empresa.objects.filter(slug="loja-do-caio-2", cnpj="11222333000181").exists())

    def test_slug_vazio_apos_slugify_e_nome_longo(self):
        self.assertEqual(self.concluir(nome_empresa="!!!").status_code, 302)
        self.assertTrue(Empresa.objects.filter(slug="empresa").exists())
        self.assertEqual(self.concluir(nome_empresa="a" * 255, cnpj="11444777000161").status_code, 302)
        self.assertTrue(Empresa.objects.filter(slug="a" * 50).exists())

    def test_onboarding_e_logout_exigem_post_com_csrf(self):
        navegador = Navegador(enforce_csrf_checks=True)
        url = reverse("empresas:onboarding")
        navegador.get(url)
        self.assertEqual(navegador.post(url, self.dados()).status_code, 403)
        dados = self.dados(csrfmiddlewaretoken=navegador.cookies["csrftoken"].value)
        self.assertEqual(navegador.post(url, dados).status_code, 302)
        self.assertIn(CONTEXTO_SESSAO, navegador.session)
        self.assertEqual(navegador.get(reverse("usuarios:logout")).status_code, 405)
        self.assertEqual(navegador.post(reverse("usuarios:logout")).status_code, 403)
        self.assertEqual(navegador.post(reverse("usuarios:logout"), {
            "csrfmiddlewaretoken": navegador.cookies["csrftoken"].value,
        }).status_code, 302)
        self.assertNotIn("_auth_user_id", navegador.session)
        self.assertNotIn(CONTEXTO_SESSAO, navegador.session)


class ConcorrenciaOnboardingTests(TransactionTestCase):
    def test_slug_concorrente_nao_duplica_empresa_nem_perde_primeira_loja(self):
        usuarios = [get_user_model().objects.create_user(cpf) for cpf in ("52998224725", "11144477735")]
        barreira = Barrier(2)
        estado = local()

        def disputar_slug(nome):
            slug = gerar_slug_disponivel(nome)
            if not getattr(estado, "tentou", False):
                estado.tentou = True
                barreira.wait(timeout=15)
            return slug

        def executar(usuario, cnpj):
            close_old_connections()
            try:
                request = RequestFactory().post("/onboarding/empresa/")
                SessionMiddleware(lambda request: None).process_request(request)
                request.user = usuario
                membro = concluir_onboarding(request, nome_empresa="Mesmo nome", cnpj=cnpj,
                                              nome_loja="Centro", cidade_loja="Franca")
                return membro.empresa_id
            finally:
                connections.close_all()

        with patch("apps.empresas.services.gerar_slug_disponivel", disputar_slug), ThreadPoolExecutor(max_workers=2) as pool:
            futuros = [pool.submit(executar, usuario, cnpj) for usuario, cnpj in zip(usuarios, ("11222333000181", "11444777000161"))]
            empresas = [f.result(timeout=30) for f in futuros]
        self.assertEqual(len(set(empresas)), 2)
        self.assertCountEqual(Empresa.objects.values_list("slug", flat=True), ["mesmo-nome", "mesmo-nome-2"])
        self.assertEqual(Loja.objects.count(), 2)
        self.assertEqual(MembroEmpresa.objects.count(), 2)
        self.assertFalse(AcessoLoja.objects.exists())
