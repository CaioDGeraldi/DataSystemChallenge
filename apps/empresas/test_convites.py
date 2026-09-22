from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connections, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, RequestFactory, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.usuarios.services import CONTEXTO_SESSAO

from .models import AcessoLoja, ConviteAcessoLoja, ConviteMembro, Empresa, Loja, MembroEmpresa
from .services import aceitar_convite, criar_convite, hash_token, revogar_convite


SENHA = "Convite!Seguro9042"
CPF = "11144477735"


class DadosConvites:
    def setUp(self):
        super().setUp()
        self.admin = get_user_model().objects.create_user("52998224725", SENHA, first_name="Ana", last_name="Silva")
        self.empresa = Empresa.objects.create(nome="Empresa A", slug="a", cnpj="11222333000181")
        self.outra = Empresa.objects.create(nome="Empresa B", slug="b", cnpj="11444777000161")
        self.membro = MembroEmpresa.objects.create(usuario=self.admin, empresa=self.empresa, papel="ADMINISTRADOR")
        self.loja = Loja.objects.create(empresa=self.empresa, nome="Centro", cidade="Franca")
        self.segunda = Loja.objects.create(empresa=self.empresa, nome="Shopping", cidade="Franca")
        self.externa = Loja.objects.create(empresa=self.outra, nome="Outra", cidade="Campinas")

    def request(self, usuario=None, membro=None):
        request = RequestFactory().post("/")
        SessionMiddleware(lambda request: None).process_request(request)
        request.user = usuario or AnonymousUser()
        if membro:
            request.session[CONTEXTO_SESSAO] = {
                "tipo_contexto": "gestao", "empresa_id": membro.empresa_id, "vinculo_id": membro.pk,
            }
        return request

    def autenticar_admin(self):
        self.client.force_login(self.admin)
        sessao = self.client.session
        sessao[CONTEXTO_SESSAO] = {"tipo_contexto": "gestao", "empresa_id": self.empresa.pk, "vinculo_id": self.membro.pk}
        sessao.save()

    def convite(self, papel="ADMINISTRADOR", lojas=(), cpf=CPF):
        return criar_convite(self.request(self.admin, self.membro), cpf=cpf, papel=papel, lojas=lojas)

    def alvo(self, **kwargs):
        return get_user_model().objects.create_user(CPF, SENHA, first_name="Original", last_name="Pessoa", **kwargs)

    def dados(self, **extra):
        return dict({"first_name": "Novo", "last_name": "Usuario", "senha": SENHA, "confirmacao": SENHA}, **extra)

    def aceitar(self, token, **extra):
        return self.client.post(reverse("empresas:aceitar_convite", args=[token]), self.dados(**extra))

    def assert_nao_aceito(self, convite):
        convite.refresh_from_db()
        self.assertIsNone(convite.aceito_em)
        self.assertFalse(MembroEmpresa.objects.filter(empresa=self.empresa, usuario__cpf=CPF).exists())
        self.assertFalse(AcessoLoja.objects.exists())


class CriacaoConviteTests(DadosConvites, TestCase):
    def test_admin_cria_hash_normaliza_cpf_validade_sem_criar_identidade(self):
        convite, token = self.convite(cpf=" 111.444.777-35 ")
        self.assertEqual(convite.cpf, CPF)
        self.assertEqual(convite.token_hash, hash_token(token))
        self.assertNotEqual(convite.token_hash, token)
        self.assertGreaterEqual(len(token), 43)
        self.assertNotIn("token", {f.name for f in ConviteMembro._meta.fields})
        self.assertNotIn(token, str(ConviteMembro.objects.values().get(pk=convite.pk)))
        self.assertEqual(convite.expira_em - convite.criado_em, timedelta(days=7))
        self.assertEqual(convite.estado, "pendente")
        self.assertEqual(convite.criado_por, self.membro)
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(MembroEmpresa.objects.count(), 1)
        self.assertFalse(AcessoLoja.objects.exists())
        self.assertFalse(ConviteAcessoLoja.objects.exists())

    def test_hash_unico_model_e_banco(self):
        convite, _ = self.convite()
        dados = dict(empresa=self.empresa, criado_por=self.membro, cpf=CPF,
                     papel="ADMINISTRADOR", token_hash=convite.token_hash, expira_em=convite.expira_em)
        with self.assertRaises(ValidationError):
            ConviteMembro.objects.create(**dados)
        with self.assertRaises(IntegrityError), transaction.atomic():
            # Bypass intencional somente para verificar a constraint SQL.
            ConviteMembro.objects.bulk_create([ConviteMembro(**dados)])

    def test_cpf_invalido_rejeitado(self):
        for cpf in ("abc", "111/444/777-35", "11144477736"):
            with self.subTest(cpf=cpf), self.assertRaises(ValidationError):
                self.convite(cpf=cpf)
        self.assertFalse(ConviteMembro.objects.exists())

    def test_escopo_admin_gestor_e_tenant_revalidados_no_service(self):
        for papel, lojas in (("ADMINISTRADOR", [self.loja]), ("GESTOR", []),
                             ("GESTOR", [self.externa]), ("INVALIDO", [])):
            with self.subTest(papel=papel, lojas=lojas), self.assertRaises(ValidationError):
                self.convite(papel, lojas)
        self.assertFalse(ConviteMembro.objects.exists())
        convite, _ = self.convite("GESTOR", [self.loja, self.segunda])
        self.assertCountEqual(convite.acessos_lojas.values_list("loja_id", flat=True), [self.loja.pk, self.segunda.pk])

    def test_form_queryset_e_post_adulterado(self):
        self.autenticar_admin()
        url = reverse("empresas:convidar_membro")
        resposta = self.client.get(url)
        self.assertCountEqual(resposta.context["form"].fields["lojas"].queryset, [self.loja, self.segunda])
        resposta = self.client.post(url, {"cpf": CPF, "papel": "GESTOR", "lojas": [self.externa.pk]})
        self.assertTrue(resposta.context["form"].errors)
        self.assertFalse(ConviteMembro.objects.exists())
        resposta = self.client.post(url, {"cpf": CPF, "papel": "ADMINISTRADOR", "empresa_id": self.outra.pk,
                                         "membro_id": 999, "criado_por": 999})
        convite = ConviteMembro.objects.get()
        self.assertEqual((convite.empresa_id, convite.criado_por_id), (self.empresa.pk, self.membro.pk))
        self.assertContains(resposta, "http://testserver/convites/")
        self.assertContains(resposta, "somente agora")
        self.assertIn("no-store", resposta["Cache-Control"])
        token = resposta.context["url_aceite"].split("/")[-3]
        self.assertEqual(hash_token(token), convite.token_hash)
        self.assertNotIn(token, str(dict(self.client.session)))
        self.assertNotContains(self.client.get(reverse("empresas:membros")), token)

    def test_admin_com_lojas_e_gestor_sem_lojas_rejeitados_por_post(self):
        self.autenticar_admin()
        for papel, lojas in (("ADMINISTRADOR", [self.loja.pk]), ("GESTOR", [])):
            with self.subTest(papel=papel):
                resposta = self.client.post(reverse("empresas:convidar_membro"), {"cpf": CPF, "papel": papel, "lojas": lojas})
                self.assertTrue(resposta.context["form"].errors)
        self.assertFalse(ConviteMembro.objects.exists())

    def test_gestor_e_inativo_nao_acessam_gestao_de_membros(self):
        for papel, ativo in (("GESTOR", True), ("ADMINISTRADOR", False)):
            self.membro.papel, self.membro.ativo = papel, ativo
            self.membro.save()
            for nome in ("membros", "convidar_membro"):
                self.autenticar_admin()
                with self.subTest(papel=papel, ativo=ativo, rota=nome):
                    self.assertEqual(self.client.get(reverse(f"empresas:{nome}")).status_code, 403)
            self.autenticar_admin()
            self.assertEqual(self.client.post(reverse("empresas:convidar_membro"), {"cpf": CPF, "papel": "ADMINISTRADOR"}).status_code, 403)
        self.assertFalse(ConviteMembro.objects.exists())

    def test_membro_existente_mesmo_inativo_nao_recebe_convite(self):
        alvo = self.alvo()
        MembroEmpresa.objects.create(usuario=alvo, empresa=self.empresa, papel="GESTOR", ativo=False)
        with self.assertRaises(ValidationError):
            self.convite()

    def test_pendente_duplicado_rejeitado_revogado_expirado_permitidos(self):
        convite, _ = self.convite()
        with self.assertRaises(ValidationError):
            self.convite(cpf="111.444.777-35")
        revogar_convite(self.request(self.admin, self.membro), convite.pk)
        novo, _ = self.convite()
        novo.expira_em = timezone.now() - timedelta(seconds=1)
        novo.save()
        terceiro, _ = self.convite()
        self.assertEqual(terceiro.estado, "pendente")
        self.assertEqual(ConviteMembro.objects.count(), 3)

    def test_criador_cross_tenant_e_troca_tenant_rejeitados(self):
        convite, _ = self.convite()
        with self.assertRaises(ValidationError):
            ConviteMembro.objects.create(empresa=self.outra, criado_por=self.membro, cpf=CPF,
                                         papel="ADMINISTRADOR", token_hash="a" * 64)
        outro = MembroEmpresa.objects.create(usuario=self.admin, empresa=self.outra, papel="ADMINISTRADOR")
        convite.empresa, convite.criado_por = self.outra, outro
        with self.assertRaises(ValidationError):
            convite.save()

    def test_model_escopo_cross_tenant_papel_unicidade_e_protect(self):
        convite, _ = self.convite("GESTOR", [self.loja])
        with self.assertRaises(ValidationError):
            ConviteAcessoLoja.objects.create(convite=convite, loja=self.externa)
        with self.assertRaises(ValidationError):
            ConviteAcessoLoja.objects.create(convite=convite, loja=self.loja)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ConviteAcessoLoja.objects.bulk_create([ConviteAcessoLoja(convite=convite, loja=self.loja)])
        for entidade in (convite, self.loja, self.membro, self.empresa):
            with self.subTest(entidade=type(entidade).__name__), self.assertRaises(ProtectedError):
                entidade.delete()
        convite.papel = "ADMINISTRADOR"
        with self.assertRaises(ValidationError):
            convite.save()
        convite.refresh_from_db()
        convite.acessos_lojas.all().delete()
        convite.papel = "ADMINISTRADOR"
        convite.save()
        with self.assertRaises(ValidationError):
            ConviteAcessoLoja.objects.create(convite=convite, loja=self.segunda)

    def test_listagem_restrita_ao_tenant(self):
        convite, _ = self.convite()
        outro = MembroEmpresa.objects.create(usuario=self.admin, empresa=self.outra, papel="ADMINISTRADOR")
        externo, token = criar_convite(self.request(self.admin, outro), cpf=CPF, papel="ADMINISTRADOR")
        self.autenticar_admin()
        resposta = self.client.get(reverse("empresas:membros"))
        self.assertQuerySetEqual(resposta.context["membros"], [self.membro])
        self.assertQuerySetEqual(resposta.context["convites"], [convite])
        self.assertNotContains(resposta, token)
        self.assertContains(resposta, "529.982.247-25")
        self.assertNotIn(externo, resposta.context["convites"])


class AceiteConviteTests(DadosConvites, TestCase):
    def test_nova_identidade_cpf_do_convite_hash_admin_sessao(self):
        convite, token = self.convite()
        resposta = self.aceitar(token, cpf=self.admin.cpf)
        self.assertRedirects(resposta, reverse("empresas:area"))
        alvo = get_user_model().objects.get(cpf=CPF)
        self.assertEqual((alvo.first_name, alvo.last_name), ("Novo", "Usuario"))
        self.assertTrue(alvo.check_password(SENHA))
        self.assertNotEqual(alvo.password, SENHA)
        self.assertEqual(get_user_model().objects.count(), 2)
        membro = MembroEmpresa.objects.get(usuario=alvo, empresa=self.empresa)
        self.assertEqual(membro.papel, "ADMINISTRADOR")
        self.assertTrue(membro.ativo)
        self.assertFalse(AcessoLoja.objects.exists())
        convite.refresh_from_db()
        self.assertEqual(convite.estado, "aceito")
        self.assertEqual(self.client.session["_auth_user_id"], str(alvo.pk))
        self.assertEqual(self.client.session[CONTEXTO_SESSAO], {
            "tipo_contexto": "gestao", "empresa_id": self.empresa.pk, "vinculo_id": membro.pk,
        })

    def test_form_nao_edita_cpf_e_existente_pede_somente_senha(self):
        _, token = self.convite()
        url = reverse("empresas:aceitar_convite", args=[token])
        form = self.client.get(url).context["form"]
        self.assertNotIn("cpf", form.fields)
        self.assertIn("confirmacao", form.fields)
        self.alvo()
        form = self.client.get(url).context["form"]
        self.assertEqual(set(form.fields), {"senha"})

    def test_existente_somente_senha_preserva_dados_globais(self):
        alvo = self.alvo()
        originais = (alvo.cpf, alvo.first_name, alvo.last_name, alvo.password)
        convite, token = self.convite()
        resposta = self.client.post(reverse("empresas:aceitar_convite", args=[token]), {"senha": SENHA, "first_name": "Alterado"})
        self.assertEqual(resposta.status_code, 302)
        alvo.refresh_from_db()
        self.assertEqual((alvo.cpf, alvo.first_name, alvo.last_name, alvo.password), originais)
        self.assertEqual(get_user_model().objects.count(), 2)
        self.assertTrue(MembroEmpresa.objects.filter(usuario=alvo, empresa=convite.empresa).exists())

    def test_existente_senha_errada_e_inativo_nao_aceitam(self):
        alvo = self.alvo()
        convite, token = self.convite()
        self.assertTrue(self.aceitar(token, senha="errada").context["form"].errors)
        self.assert_nao_aceito(convite)
        alvo.is_active = False
        alvo.save()
        self.assertTrue(self.aceitar(token).context["form"].errors)
        self.assert_nao_aceito(convite)

    def test_autenticado_mesmo_cpf_sem_senha_substitui_contexto(self):
        alvo = self.alvo()
        anterior = MembroEmpresa.objects.create(usuario=alvo, empresa=self.outra, papel="GESTOR")
        _, token = self.convite()
        self.client.force_login(alvo)
        sessao = self.client.session
        sessao[CONTEXTO_SESSAO] = {"tipo_contexto": "gestao", "empresa_id": self.outra.pk, "vinculo_id": anterior.pk}
        sessao.save()
        resposta = self.client.post(reverse("empresas:aceitar_convite", args=[token]), {})
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(alvo.membros_empresas.count(), 2)
        self.assertEqual(self.client.session[CONTEXTO_SESSAO]["empresa_id"], self.empresa.pk)
        self.assertEqual(len(self.client.session[CONTEXTO_SESSAO]), 3)

    def test_autenticado_outro_cpf_nao_aceita_mesmo_com_senha_alvo(self):
        self.alvo()
        convite, token = self.convite()
        self.autenticar_admin()
        self.assertEqual(self.aceitar(token).status_code, 403)
        self.assert_nao_aceito(convite)

    def test_nova_identidade_validacoes(self):
        convite, token = self.convite()
        for dados in ({"first_name": ""}, {"last_name": ""}, {"senha": ""},
                      {"confirmacao": ""}, {"confirmacao": "diferente"},
                      {"senha": "123", "confirmacao": "123"}):
            with self.subTest(dados=dados):
                self.assertTrue(self.aceitar(token, **dados).context["form"].errors)
                self.assert_nao_aceito(convite)
                self.assertFalse(get_user_model().objects.filter(cpf=CPF).exists())

    def test_password_validators_configurados(self):
        convite, token = self.convite()
        with self.settings(AUTH_PASSWORD_VALIDATORS=[{
            "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 100},
        }]):
            self.assertTrue(self.aceitar(token).context["form"].errors)
        self.assert_nao_aceito(convite)

    def test_identidade_surgida_entre_get_e_post_e_reutilizada(self):
        _, token = self.convite()
        self.client.get(reverse("empresas:aceitar_convite", args=[token]))
        alvo = self.alvo()
        self.assertEqual(self.aceitar(token, first_name="Outro").status_code, 302)
        alvo.refresh_from_db()
        self.assertEqual(alvo.first_name, "Original")
        self.assertEqual(get_user_model().objects.count(), 2)

    def test_service_revalida_identidade_surgida_apos_form(self):
        convite, token = self.convite()
        original = get_user_model().objects.create_user
        # A identidade é criada ao entrar no helper, depois da consulta do aceite.
        from apps.usuarios.services import resolver_identidade
        def resolver_com_disputa(**kwargs):
            original(CPF, SENHA, first_name="Original", last_name="Pessoa")
            return resolver_identidade(**kwargs)
        with patch("apps.empresas.services.resolver_identidade", side_effect=resolver_com_disputa):
            self.assertEqual(self.aceitar(token).status_code, 302)
        self.assertEqual(get_user_model().objects.get(cpf=CPF).first_name, "Original")
        self.assertEqual(get_user_model().objects.count(), 2)

    def test_gestor_recebe_exatamente_lojas_persistidas(self):
        _, token = self.convite("GESTOR", [self.loja, self.segunda])
        self.assertEqual(self.aceitar(token, lojas=[self.externa.pk], papel="ADMINISTRADOR").status_code, 302)
        membro = MembroEmpresa.objects.get(usuario__cpf=CPF, empresa=self.empresa)
        self.assertEqual(membro.papel, "GESTOR")
        self.assertTrue(membro.ativo)
        self.assertCountEqual(membro.acessos_lojas.values_list("loja_id", flat=True), [self.loja.pk, self.segunda.pk])

    def test_aceite_revalida_escopo_corrompido_ou_vazio(self):
        convite, token = self.convite("GESTOR", [self.loja])
        # Simula corrupção externa aos caminhos normais do domínio.
        convite.acessos_lojas.update(loja=self.externa)
        self.assertTrue(self.aceitar(token).context["form"].errors)
        self.assert_nao_aceito(convite)
        convite.acessos_lojas.all().delete()
        self.assertTrue(self.aceitar(token).context["form"].errors)
        self.assert_nao_aceito(convite)
        self.assertFalse(get_user_model().objects.filter(cpf=CPF).exists())

    def test_token_inexistente_alterado_expirado_revogado(self):
        convite, token = self.convite()
        for invalido in ("inexistente", token + "x"):
            self.assertEqual(self.aceitar(invalido).status_code, 403)
        convite.expira_em = timezone.now() - timedelta(seconds=1)
        convite.save()
        self.assertEqual(self.aceitar(token).status_code, 403)
        convite.expira_em = timezone.now() + timedelta(days=1)
        convite.revogado_em = timezone.now()
        convite.save()
        self.assertEqual(self.aceitar(token).status_code, 403)
        self.assert_nao_aceito(convite)

    def test_token_uso_unico(self):
        convite, token = self.convite()
        self.assertEqual(self.aceitar(token).status_code, 302)
        convite.refresh_from_db()
        aceito_em = convite.aceito_em
        self.assertEqual(self.aceitar(token).status_code, 403)
        convite.refresh_from_db()
        self.assertEqual(convite.aceito_em, aceito_em)
        self.assertEqual(MembroEmpresa.objects.filter(usuario__cpf=CPF).count(), 1)

    def test_membro_criado_apos_convite_impede_aceite(self):
        alvo = self.alvo()
        convite, token = self.convite()
        MembroEmpresa.objects.create(usuario=alvo, empresa=self.empresa, papel="GESTOR")
        self.assertTrue(self.aceitar(token).context["form"].errors)
        convite.refresh_from_db()
        self.assertIsNone(convite.aceito_em)
        self.assertEqual(alvo.membros_empresas.count(), 1)

    def test_rollback_membro_acesso_parcial_e_marcacao(self):
        convite, token = self.convite("GESTOR", [self.loja, self.segunda])
        original = AcessoLoja.objects.create
        contador = 0
        def acesso_parcial(**kwargs):
            nonlocal contador
            contador += 1
            if contador == 2:
                raise IntegrityError("falha simulada")
            return original(**kwargs)
        for alvo, efeito in (
            ("MembroEmpresa.objects.create", IntegrityError("falha simulada")),
            ("AcessoLoja.objects.create", acesso_parcial),
            ("ConviteMembro.save", IntegrityError("falha simulada")),
        ):
            with self.subTest(alvo=alvo):
                with patch(f"apps.empresas.services.{alvo}", side_effect=efeito):
                    with self.assertRaises(IntegrityError):
                        self.aceitar(token)
                self.assert_nao_aceito(convite)
                self.assertFalse(get_user_model().objects.filter(cpf=CPF).exists())
                self.assertNotIn("_auth_user_id", self.client.session)
                self.assertNotIn(CONTEXTO_SESSAO, self.client.session)

    def test_membro_desativado_perde_acesso_apos_aceite(self):
        _, token = self.convite()
        self.aceitar(token)
        membro = MembroEmpresa.objects.get(usuario__cpf=CPF)
        membro.ativo = False
        membro.save()
        self.assertEqual(self.client.get(reverse("empresas:area")).status_code, 403)
        self.assertNotIn(CONTEXTO_SESSAO, self.client.session)

    def test_falha_preserva_identidade_existente_e_contexto_anterior(self):
        alvo = self.alvo()
        anterior = MembroEmpresa.objects.create(usuario=alvo, empresa=self.outra, papel="GESTOR")
        convite, token = self.convite()
        request = self.request(alvo, anterior)
        contexto = dict(request.session[CONTEXTO_SESSAO])
        with patch("apps.empresas.services.ConviteMembro.save", side_effect=IntegrityError("falha simulada")):
            with self.assertRaises(IntegrityError):
                aceitar_convite(request, token)
        self.assert_nao_aceito(convite)
        alvo.refresh_from_db()
        self.assertTrue(alvo.check_password(SENHA))
        self.assertEqual(alvo.first_name, "Original")
        self.assertEqual(alvo.membros_empresas.count(), 1)
        self.assertEqual(request.session[CONTEXTO_SESSAO], contexto)

    def test_service_revalida_usuario_autenticado_inativo(self):
        from django.core.exceptions import PermissionDenied
        alvo = self.alvo()
        convite, token = self.convite()
        request = self.request(alvo)
        alvo.is_active = False
        alvo.save()
        with self.assertRaises(PermissionDenied):
            aceitar_convite(request, token)
        self.assert_nao_aceito(convite)


class RevogacaoConviteTests(DadosConvites, TestCase):
    def test_expirado_nao_pode_ser_revogado_nem_oferece_acao_na_tela(self):
        convite, _ = self.convite()
        convite.expira_em = timezone.now() - timedelta(seconds=1)
        convite.save(update_fields=["expira_em"])
        self.assertEqual(convite.estado, "expirado")
        self.assertFalse(convite.pode_revogar)

        with self.assertRaises(ValidationError):
            revogar_convite(self.request(self.admin, self.membro), convite.pk)

        convite.refresh_from_db()
        self.assertIsNone(convite.revogado_em)
        self.assertEqual(convite.estado, "expirado")
        self.assertFalse(convite.pode_revogar)

        self.autenticar_admin()
        resposta = self.client.get(reverse("empresas:membros"))
        self.assertContains(resposta, "Expirado")
        self.assertNotContains(resposta, reverse("empresas:revogar_convite", args=[convite.pk]))
        self.assertNotContains(resposta, "Revogar")

    def test_admin_revoga_sem_delete_e_bloqueia_aceite(self):
        convite, token = self.convite()
        self.autenticar_admin()
        self.assertEqual(self.client.post(reverse("empresas:revogar_convite", args=[convite.pk])).status_code, 302)
        convite.refresh_from_db()
        self.assertEqual(convite.estado, "revogado")
        self.client.logout()
        self.assertEqual(self.aceitar(token).status_code, 403)

    def test_outro_tenant_gestor_e_inativo_nao_revogam(self):
        convite, _ = self.convite()
        outro = MembroEmpresa.objects.create(usuario=self.admin, empresa=self.outra, papel="ADMINISTRADOR")
        self.client.force_login(self.admin)
        sessao = self.client.session
        sessao[CONTEXTO_SESSAO] = {"tipo_contexto": "gestao", "empresa_id": self.outra.pk, "vinculo_id": outro.pk}
        sessao.save()
        url = reverse("empresas:revogar_convite", args=[convite.pk])
        self.assertEqual(self.client.post(url).status_code, 403)
        for papel, ativo in (("GESTOR", True), ("ADMINISTRADOR", False)):
            self.membro.papel, self.membro.ativo = papel, ativo
            self.membro.save()
            self.autenticar_admin()
            self.assertEqual(self.client.post(url).status_code, 403)
        convite.refresh_from_db()
        self.assertIsNone(convite.revogado_em)

    def test_aceito_e_revogado_nao_podem_ser_revogados_novamente(self):
        convite, token = self.convite()
        self.aceitar(token)
        with self.assertRaises(ValidationError):
            revogar_convite(self.request(self.admin, self.membro), convite.pk)
        convite.refresh_from_db()
        self.assertIsNone(convite.revogado_em)
        outro, _ = self.convite(cpf="12345678909")
        revogar_convite(self.request(self.admin, self.membro), outro.pk)
        with self.assertRaises(ValidationError):
            revogar_convite(self.request(self.admin, self.membro), outro.pk)

    def test_post_csrf_criacao_aceite_e_revogacao(self):
        convite, token = self.convite()
        navegador = Client(enforce_csrf_checks=True)
        url_aceite = reverse("empresas:aceitar_convite", args=[token])
        self.assertEqual(navegador.post(url_aceite, self.dados()).status_code, 403)
        navegador.force_login(self.admin)
        sessao = navegador.session
        sessao[CONTEXTO_SESSAO] = {"tipo_contexto": "gestao", "empresa_id": self.empresa.pk, "vinculo_id": self.membro.pk}
        sessao.save()
        url = reverse("empresas:revogar_convite", args=[convite.pk])
        self.assertEqual(navegador.get(url).status_code, 405)
        self.assertEqual(navegador.post(url).status_code, 403)
        self.assertEqual(navegador.post(reverse("empresas:convidar_membro"), {"cpf": CPF, "papel": "ADMINISTRADOR"}).status_code, 403)
        navegador.get(reverse("empresas:membros"))
        self.assertEqual(navegador.post(url, {"csrfmiddlewaretoken": navegador.cookies["csrftoken"].value}).status_code, 302)


class ConcorrenciaConviteTests(DadosConvites, TransactionTestCase):
    def executar_em_paralelo(self, operacao):
        barreira = Barrier(2)
        def executar():
            close_old_connections()
            try:
                barreira.wait(timeout=15)
                return operacao()
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futuros = [pool.submit(executar) for _ in range(2)]
            return [f.result(timeout=45) for f in futuros]

    def test_dois_aceites_concorrentes_apenas_um_vinculo_e_aceite(self):
        from django.core.exceptions import PermissionDenied
        convite, token = self.convite("GESTOR", [self.loja, self.segunda])
        def aceitar():
            try:
                membro = aceitar_convite(self.request(), token, **self.dados())
                return membro.pk
            except PermissionDenied:
                return None
        resultados = self.executar_em_paralelo(aceitar)
        self.assertEqual(sum(r is not None for r in resultados), 1)
        self.assertEqual(get_user_model().objects.filter(cpf=CPF).count(), 1)
        self.assertEqual(MembroEmpresa.objects.filter(usuario__cpf=CPF).count(), 1)
        self.assertEqual(AcessoLoja.objects.count(), 2)
        convite.refresh_from_db()
        self.assertEqual(convite.estado, "aceito")
        self.assertEqual(ConviteMembro.objects.filter(aceito_em__isnull=False).count(), 1)

    def test_criacao_concorrente_mesmo_cpf_empresa_nao_duplica_pendente(self):
        def criar():
            try:
                convite, _ = self.convite()
                return convite.pk
            except ValidationError:
                return None
        resultados = self.executar_em_paralelo(criar)
        self.assertEqual(sum(r is not None for r in resultados), 1)
        self.assertEqual(ConviteMembro.objects.count(), 1)
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(MembroEmpresa.objects.count(), 1)
