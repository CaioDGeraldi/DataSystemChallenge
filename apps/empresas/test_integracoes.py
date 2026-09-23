import secrets
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.contrib.messages import get_messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from apps.usuarios.services import CONTEXTO_SESSAO

from .models import CredencialAcessoLoja, CredencialIntegracao, Empresa, Loja, MembroEmpresa
from .services import (
    autenticar_credencial, criar_credencial, desativar_credencial,
    exigir_loja_autorizada, lojas_autorizadas,
)


class DadosIntegracoes:
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.usuario = get_user_model().objects.create_user("52998224725")
        cls.empresa = Empresa.objects.create(nome="Empresa A", slug="a", cnpj="11222333000181")
        cls.outra = Empresa.objects.create(nome="Empresa B", slug="b", cnpj="11444777000161")
        cls.membro = MembroEmpresa.objects.create(usuario=cls.usuario, empresa=cls.empresa, papel="ADMINISTRADOR")
        cls.outro_membro = MembroEmpresa.objects.create(usuario=cls.usuario, empresa=cls.outra, papel="ADMINISTRADOR")
        cls.loja = Loja.objects.create(empresa=cls.empresa, nome="Centro", cidade="Araras")
        cls.segunda = Loja.objects.create(empresa=cls.empresa, nome="Shopping", cidade="Araras")
        cls.externa = Loja.objects.create(empresa=cls.outra, nome="Outra", cidade="Campinas")

    def request(self, membro=None):
        membro = membro or self.membro
        request = RequestFactory().post("/gestao/integracoes/nova/")
        request.user = self.usuario
        request.session = {CONTEXTO_SESSAO: {
            "tipo_contexto": "gestao", "empresa_id": membro.empresa_id, "vinculo_id": membro.pk,
        }}
        return request

    def autenticar_admin(self, client=None, membro=None):
        client = client or self.client
        client.force_login(self.usuario)
        sessao = client.session
        sessao[CONTEXTO_SESSAO] = self.request(membro).session[CONTEXTO_SESSAO]
        sessao.save()

    def criar(self, escopo="EMPRESA", lojas=(), membro=None):
        return criar_credencial(self.request(membro), nome="PDV", escopo=escopo, lojas=lojas)


class CredenciaisDominioTests(DadosIntegracoes, TestCase):
    def test_empresa_cria_somente_hash_sem_identidade_humana_nova(self):
        credencial, chave = self.criar()
        identificador, segredo = chave.split(".")
        self.assertEqual(credencial.identificador, identificador)
        self.assertEqual(credencial.empresa, self.empresa)
        self.assertEqual(credencial.criada_por, self.membro)
        self.assertEqual(credencial.escopo, "EMPRESA")
        self.assertTrue(credencial.ativa)
        self.assertIsNotNone(credencial.criada_em)
        self.assertIsNone(credencial.ultimo_uso_em)
        self.assertTrue(check_password(segredo, credencial.segredo_hash))
        self.assertFalse(check_password(secrets.token_urlsafe(32), credencial.segredo_hash))
        self.assertGreaterEqual(len(identificador), 24)
        self.assertGreaterEqual(len(segredo), 43)
        self.assertFalse(CredencialAcessoLoja.objects.exists())
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertNotIn(segredo, str(CredencialIntegracao.objects.values().get()))
        self.assertNotIn(segredo, str(vars(credencial)))
        self.assertNotIn(segredo, str(credencial))
        self.assertNotIn("segredo", {f.name for f in CredencialIntegracao._meta.fields})

    def test_geracao_independente_por_credencial(self):
        primeira, chave_a = self.criar()
        segunda, chave_b = self.criar()
        self.assertNotEqual(primeira.identificador, segunda.identificador)
        self.assertNotEqual(chave_a.split(".")[1], chave_b.split(".")[1])
        self.assertNotEqual(primeira.segredo_hash, segunda.segredo_hash)

    def test_lojas_cria_relacoes_explicitas(self):
        credencial, _ = self.criar("LOJAS", [self.loja, self.segunda])
        self.assertCountEqual(credencial.acessos_lojas.values_list("loja_id", flat=True), [self.loja.pk, self.segunda.pk])

    def test_service_rejeita_escopo_invalido_vazio_empresa_com_lojas_e_cross_tenant(self):
        for escopo, lojas in (("LOJAS", []), ("EMPRESA", [self.loja]),
                              ("LOJAS", [self.loja, self.externa]), ("INVALIDO", [])):
            with self.subTest(escopo=escopo, lojas=lojas), self.assertRaises(ValidationError):
                self.criar(escopo, lojas)
        self.assertFalse(CredencialIntegracao.objects.exists())
        self.assertFalse(CredencialAcessoLoja.objects.exists())

    def test_empresa_escopo_imutaveis_em_clean_save_e_save_parcial(self):
        credencial, _ = self.criar("LOJAS", [self.loja])
        for campo, valor in (("empresa_id", self.outra.pk), ("escopo", "EMPRESA")):
            for metodo in ("clean", "save", "parcial"):
                with self.subTest(campo=campo, metodo=metodo):
                    setattr(credencial, campo, valor)
                    with self.assertRaises(ValidationError):
                        if metodo == "parcial":
                            credencial.save(update_fields=[campo])
                        else:
                            getattr(credencial, metodo)()
                    credencial.refresh_from_db()
                    self.assertEqual((credencial.empresa_id, credencial.escopo), (self.empresa.pk, "LOJAS"))

    def test_identificador_unico_no_model_e_banco(self):
        credencial, _ = self.criar()
        dados = dict(empresa=self.empresa, criada_por=self.membro, nome="Outro PDV",
                     identificador=credencial.identificador, segredo_hash=credencial.segredo_hash, escopo="EMPRESA")
        with self.assertRaises(ValidationError):
            CredencialIntegracao.objects.create(**dados)
        with self.assertRaises(IntegrityError), transaction.atomic():
            # Bypass deliberado somente para testar a constraint SQL.
            CredencialIntegracao.objects.bulk_create([CredencialIntegracao(**dados)])

    def test_model_rejeita_segredo_bruto_e_criador_externo(self):
        credencial, chave = self.criar()
        credencial.segredo_hash = chave.split(".")[1]
        with self.assertRaises(ValidationError):
            credencial.save()
        credencial.refresh_from_db()
        credencial.criada_por = self.outro_membro
        with self.assertRaises(ValidationError):
            credencial.save()

    def test_acesso_cross_tenant_e_corporativo_rejeitados_por_clean_create_e_save(self):
        restrita, _ = self.criar("LOJAS", [self.loja])
        corporativa, _ = self.criar()
        for credencial, loja in ((restrita, self.externa), (corporativa, self.segunda)):
            with self.assertRaises(ValidationError):
                CredencialAcessoLoja(credencial=credencial, loja=loja).clean()
            with self.assertRaises(ValidationError):
                CredencialAcessoLoja.objects.create(credencial=credencial, loja=loja)
        acesso = restrita.acessos_lojas.get()
        acesso.loja = self.externa
        with self.assertRaises(ValidationError):
            acesso.save(update_fields=["loja"])

    def test_acesso_unico_e_relacoes_protegidas(self):
        credencial, _ = self.criar("LOJAS", [self.loja])
        with self.assertRaises(ValidationError):
            CredencialAcessoLoja.objects.create(credencial=credencial, loja=self.loja)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CredencialAcessoLoja.objects.bulk_create([CredencialAcessoLoja(credencial=credencial, loja=self.loja)])
        for entidade in (credencial, self.loja, self.membro, self.empresa):
            with self.subTest(entidade=type(entidade).__name__), self.assertRaises(ProtectedError):
                entidade.delete()

    def test_criacao_transacional_desfaz_credencial_e_acesso_parcial(self):
        original = CredencialAcessoLoja.objects.create
        chamadas = 0

        def falhar_no_segundo(**kwargs):
            nonlocal chamadas
            chamadas += 1
            if chamadas == 2:
                raise IntegrityError("Falha simulada")
            return original(**kwargs)

        with patch("apps.empresas.services.CredencialAcessoLoja.objects.create", side_effect=falhar_no_segundo):
            with self.assertRaises(IntegrityError):
                self.criar("LOJAS", [self.loja, self.segunda])
        self.assertFalse(CredencialIntegracao.objects.exists())
        self.assertFalse(CredencialAcessoLoja.objects.exists())

    def test_services_exigem_admin_ativo_e_usuario_ativo(self):
        credencial, _ = self.criar()
        for papel, ativo in (("GESTOR", True), ("ADMINISTRADOR", False)):
            self.membro.papel, self.membro.ativo = papel, ativo
            self.membro.save()
            with self.assertRaises(PermissionDenied):
                self.criar()
            with self.assertRaises(PermissionDenied):
                desativar_credencial(self.request(), credencial.pk)
        self.membro.papel, self.membro.ativo = "ADMINISTRADOR", True
        self.membro.save()
        self.usuario.is_active = False
        self.usuario.save()
        with self.assertRaises(PermissionDenied):
            self.criar()
        credencial.refresh_from_db()
        self.assertTrue(credencial.ativa)

    def test_empresa_inclui_lojas_futuras_e_rejeita_externa(self):
        credencial, _ = self.criar()
        self.assertQuerySetEqual(lojas_autorizadas(credencial), [self.loja, self.segunda])
        nova = Loja.objects.create(empresa=self.empresa, nome="Nova", cidade="Araras")
        self.assertQuerySetEqual(lojas_autorizadas(credencial), [self.loja, nova, self.segunda])
        self.assertEqual(exigir_loja_autorizada(credencial, nova), nova)
        with self.assertRaises(PermissionDenied):
            exigir_loja_autorizada(credencial, self.externa)
        self.assertFalse(CredencialAcessoLoja.objects.exists())

    def test_lojas_restritas_helper_rejeita_externa_e_nao_relacionada(self):
        credencial, _ = self.criar("LOJAS", [self.loja])
        self.assertQuerySetEqual(lojas_autorizadas(credencial), [self.loja])
        self.assertEqual(exigir_loja_autorizada(credencial, self.loja), self.loja)
        for loja in (self.segunda, self.externa):
            with self.assertRaises(PermissionDenied):
                exigir_loja_autorizada(credencial, loja)

    def test_helpers_revalidam_objetos_adulterados_relacao_corrompida_e_inativa(self):
        credencial, _ = self.criar("LOJAS", [self.loja])
        credencial.escopo = "EMPRESA"
        self.externa.empresa_id = self.empresa.pk
        for loja in (self.segunda, self.externa):
            with self.assertRaises(PermissionDenied):
                exigir_loja_autorizada(credencial, loja)
        # Corrupção fora dos caminhos normais do domínio não pode vazar outra Empresa.
        credencial.acessos_lojas.update(loja_id=self.externa.pk)
        self.assertFalse(lojas_autorizadas(credencial).exists())
        desativar_credencial(self.request(), credencial.pk)
        self.assertFalse(lojas_autorizadas(credencial).exists())
        with self.assertRaises(PermissionDenied):
            exigir_loja_autorizada(credencial, self.loja)

    def test_desativacao_preserva_dados_revoga_autenticacao_e_nao_aceita_outro_tenant(self):
        credencial, chave = self.criar()
        with self.assertRaises(PermissionDenied):
            desativar_credencial(self.request(self.outro_membro), credencial.pk)
        self.assertEqual(autenticar_credencial(chave).pk, credencial.pk)
        desativar_credencial(self.request(), credencial.pk)
        self.assertIsNone(autenticar_credencial(chave))
        credencial.refresh_from_db()
        self.assertFalse(credencial.ativa)
        self.assertEqual(CredencialIntegracao.objects.count(), 1)


class EscopoEmitidoTests(DadosIntegracoes, TestCase):
    def test_emissao_com_duas_lojas_nao_permite_acrescentar_terceira(self):
        credencial, _ = self.criar("LOJAS", [self.loja, self.segunda])
        terceira = Loja.objects.create(empresa=self.empresa, nome="Terceira", cidade="Araras")
        for criar in (
            lambda: CredencialAcessoLoja.objects.create(credencial=credencial, loja=terceira),
            lambda: credencial.acessos_lojas.create(loja=terceira),
            lambda: CredencialAcessoLoja(credencial=credencial, loja=terceira).save(),
        ):
            with self.assertRaises(ValidationError):
                criar()
        self.assertQuerySetEqual(lojas_autorizadas(credencial), [self.loja, self.segunda])

    def test_relacao_nao_pode_trocar_loja_propria_ou_cross_tenant(self):
        credencial, _ = self.criar("LOJAS", [self.loja])
        acesso = credencial.acessos_lojas.get()
        for loja in (self.segunda, self.externa):
            for metodo in ("clean", "save", "parcial"):
                with self.subTest(loja=loja.pk, metodo=metodo):
                    acesso.loja = loja
                    with self.assertRaises(ValidationError):
                        if metodo == "parcial":
                            acesso.save(update_fields=["loja"])
                        else:
                            getattr(acesso, metodo)()
                    acesso.refresh_from_db()
                    self.assertEqual(acesso.loja_id, self.loja.pk)

    def test_relacao_nao_pode_mudar_para_outra_credencial(self):
        antiga, _ = self.criar("LOJAS", [self.loja])
        nova, _ = self.criar("LOJAS", [self.segunda])
        acesso = antiga.acessos_lojas.get()
        acesso.credencial = nova
        with self.assertRaises(ValidationError):
            acesso.save(update_fields=["credencial"])
        self.assertQuerySetEqual(lojas_autorizadas(antiga), [self.loja])
        self.assertQuerySetEqual(lojas_autorizadas(nova), [self.segunda])

    def test_nao_remove_relacao_por_instancia_queryset_ou_manager_reverso(self):
        credencial, _ = self.criar("LOJAS", [self.loja, self.segunda])
        acesso = credencial.acessos_lojas.get(loja=self.loja)
        for remover in (
            lambda: acesso.delete(),
            lambda: CredencialAcessoLoja.objects.filter(pk=acesso.pk).delete(),
            lambda: credencial.acessos_lojas.all().delete(),
        ):
            with self.assertRaises(ValidationError), transaction.atomic():
                remover()
            self.assertQuerySetEqual(lojas_autorizadas(credencial), [self.loja, self.segunda])

    def test_desativacao_preserva_escopo_e_nova_credencial_permite_outro_conjunto(self):
        antiga, chave_antiga = self.criar("LOJAS", [self.loja, self.segunda])
        desativar_credencial(self.request(), antiga.pk)
        self.assertIsNone(autenticar_credencial(chave_antiga))
        self.assertCountEqual(antiga.acessos_lojas.values_list("loja_id", flat=True), [self.loja.pk, self.segunda.pk])
        nova, chave_nova = self.criar("LOJAS", [self.segunda])
        self.assertNotEqual(nova.pk, antiga.pk)
        self.assertEqual(autenticar_credencial(chave_nova).pk, nova.pk)
        self.assertQuerySetEqual(lojas_autorizadas(nova), [self.segunda])
        with self.assertRaises(ValidationError), transaction.atomic():
            antiga.acessos_lojas.all().delete()

    def test_emissao_de_outra_credencial_nao_reabre_escopo_antigo(self):
        antiga, _ = self.criar("LOJAS", [self.loja])
        original = CredencialAcessoLoja.objects.create

        def ampliar_antiga(**kwargs):
            return original(credencial=antiga, loja=self.segunda)

        with patch("apps.empresas.services.CredencialAcessoLoja.objects.create", side_effect=ampliar_antiga):
            with self.assertRaises(ValidationError):
                self.criar("LOJAS", [self.segunda])
        self.assertEqual(CredencialIntegracao.objects.count(), 1)
        self.assertQuerySetEqual(lojas_autorizadas(antiga), [self.loja])
        # Uma emissão posterior continua funcionando após a falha transacional.
        nova, _ = self.criar("LOJAS", [self.segunda])
        self.assertQuerySetEqual(lojas_autorizadas(nova), [self.segunda])

    def test_empresa_permanece_sem_relacoes_individuais(self):
        credencial, _ = self.criar()
        with self.assertRaises(ValidationError):
            credencial.acessos_lojas.create(loja=self.loja)
        self.assertFalse(credencial.acessos_lojas.exists())
        self.assertQuerySetEqual(lojas_autorizadas(credencial), [self.loja, self.segunda])


class IntegracoesHTTPTests(DadosIntegracoes, TestCase):
    def test_admin_cria_chave_somente_na_resposta_sem_sessao_messages_ou_hash(self):
        self.autenticar_admin()
        resposta = self.client.post(reverse("empresas:nova_integracao"), {
            "nome": "PDV", "escopo": "EMPRESA", "empresa_id": self.outra.pk,
            "criada_por": self.outro_membro.pk,
        })
        self.assertEqual(resposta.status_code, 200)
        self.assertTemplateUsed(resposta, "datasystem/gestor/integracao_criada.html")
        chave = resposta.context["chave"]
        credencial = CredencialIntegracao.objects.get()
        self.assertEqual((credencial.empresa_id, credencial.criada_por_id), (self.empresa.pk, self.membro.pk))
        self.assertTrue(check_password(chave.split(".")[1], credencial.segredo_hash))
        self.assertContains(resposta, f"X-API-Key: {chave}")
        self.assertContains(resposta, "não poderá ser exibido novamente")
        self.assertNotContains(resposta, credencial.segredo_hash)
        self.assertIn("no-store", resposta["Cache-Control"])
        self.assertEqual(resposta["Referrer-Policy"], "no-referrer")
        self.assertNotIn(chave, str(dict(self.client.session)))
        self.assertNotIn(chave, str(list(get_messages(resposta.wsgi_request))))
        for rota in ("integracoes", "nova_integracao"):
            posterior = self.client.get(reverse(f"empresas:{rota}"))
            self.assertNotContains(posterior, chave)
            self.assertNotContains(posterior, chave.split(".")[1])
            self.assertNotContains(posterior, credencial.segredo_hash)

    def test_listagem_somente_empresa_ativa_e_campos_publicos(self):
        propria, _ = self.criar()
        externa, _ = self.criar(membro=self.outro_membro)
        self.autenticar_admin()
        resposta = self.client.get(reverse("empresas:integracoes"))
        dados = list(resposta.context["credenciais"])
        self.assertEqual([c["id"] for c in dados], [propria.pk])
        self.assertEqual(set(dados[0]), {"id", "nome", "identificador", "escopo", "ativa", "criada_em", "ultimo_uso_em"})
        self.assertContains(resposta, propria.identificador)
        self.assertNotContains(resposta, externa.identificador)
        self.assertNotContains(resposta, propria.segredo_hash)

    def test_queryset_limitado_e_post_adulterado_rejeitado(self):
        self.autenticar_admin()
        url = reverse("empresas:nova_integracao")
        form = self.client.get(url).context["form"]
        self.assertQuerySetEqual(form.fields["lojas"].queryset, [self.loja, self.segunda])
        self.assertEqual(set(form.fields), {"nome", "escopo", "lojas"})
        for escopo, lojas in (("LOJAS", [self.externa.pk]), ("LOJAS", []), ("EMPRESA", [self.loja.pk])):
            with self.subTest(escopo=escopo, lojas=lojas):
                resposta = self.client.post(url, {"nome": "PDV", "escopo": escopo, "lojas": lojas})
                self.assertTrue(resposta.context["form"].errors)
        self.assertFalse(CredencialIntegracao.objects.exists())

    def test_criacao_restrita_via_web(self):
        self.autenticar_admin()
        resposta = self.client.post(reverse("empresas:nova_integracao"), {
            "nome": "PDV", "escopo": "LOJAS", "lojas": [self.loja.pk, self.segunda.pk],
        })
        self.assertEqual(resposta.status_code, 200)
        credencial = CredencialIntegracao.objects.get()
        self.assertEqual(credencial.escopo, "LOJAS")
        self.assertEqual(credencial.acessos_lojas.count(), 2)

    def test_gestor_e_membro_inativo_recebem_403_em_todas_as_operacoes(self):
        credencial, _ = self.criar()
        for papel, ativo in (("GESTOR", True), ("ADMINISTRADOR", False)):
            self.membro.papel, self.membro.ativo = papel, ativo
            self.membro.save()
            for metodo, url in (
                ("get", reverse("empresas:integracoes")),
                ("get", reverse("empresas:nova_integracao")),
                ("post", reverse("empresas:nova_integracao")),
                ("post", reverse("empresas:desativar_integracao", args=[credencial.pk])),
            ):
                with self.subTest(papel=papel, ativo=ativo, metodo=metodo, url=url):
                    self.autenticar_admin()
                    self.assertEqual(getattr(self.client, metodo)(url).status_code, 403)
        credencial.refresh_from_db()
        self.assertTrue(credencial.ativa)
        self.assertEqual(CredencialIntegracao.objects.count(), 1)

    def test_sem_login_sem_contexto_e_contexto_adulterado_nao_autorizam(self):
        credencial, _ = self.criar()
        rotas = [reverse("empresas:integracoes"), reverse("empresas:nova_integracao"),
                 reverse("empresas:desativar_integracao", args=[credencial.pk])]
        for url in rotas:
            self.assertEqual(self.client.post(url).status_code, 302)
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.get(rotas[0]).status_code, 403)
        self.autenticar_admin()
        sessao = self.client.session
        sessao[CONTEXTO_SESSAO] = dict(self.request().session[CONTEXTO_SESSAO], empresa_id=self.outra.pk)
        sessao.save()
        self.assertEqual(self.client.get(rotas[0]).status_code, 403)

    def test_desativacao_post_sem_delete_get_405_e_outro_tenant_403(self):
        credencial, chave = self.criar()
        url = reverse("empresas:desativar_integracao", args=[credencial.pk])
        self.autenticar_admin(membro=self.outro_membro)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.autenticar_admin()
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertRedirects(self.client.post(url), reverse("empresas:integracoes"))
        credencial.refresh_from_db()
        self.assertFalse(credencial.ativa)
        self.assertIsNone(autenticar_credencial(chave))
        self.assertEqual(CredencialIntegracao.objects.count(), 1)

    def test_csrf_obrigatorio_na_criacao_e_desativacao(self):
        navegador = Client(enforce_csrf_checks=True)
        self.autenticar_admin(navegador)
        nova = reverse("empresas:nova_integracao")
        dados = {"nome": "PDV", "escopo": "EMPRESA"}
        self.assertEqual(navegador.post(nova, dados).status_code, 403)
        self.assertFalse(CredencialIntegracao.objects.exists())
        navegador.get(nova)
        token = navegador.cookies["csrftoken"].value
        self.assertEqual(navegador.post(nova, dict(dados, csrfmiddlewaretoken=token)).status_code, 200)
        credencial = CredencialIntegracao.objects.get()
        url = reverse("empresas:desativar_integracao", args=[credencial.pk])
        self.assertEqual(navegador.post(url).status_code, 403)
        credencial.refresh_from_db()
        self.assertTrue(credencial.ativa)
        self.assertEqual(navegador.post(url, {"csrfmiddlewaretoken": token}).status_code, 302)
        credencial.refresh_from_db()
        self.assertFalse(credencial.ativa)
