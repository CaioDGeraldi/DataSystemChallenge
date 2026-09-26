from dataclasses import FrozenInstanceError, asdict
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from apps.clientes.models import Cliente
from apps.usuarios.services import CONTEXTO_SESSAO

from .models import ConfiguracaoFidelidadeEmpresa, Empresa, Loja, MembroEmpresa, OverrideFidelidadeLoja
from .parametros import ConfiguracaoEfetiva, PADROES_FIDELIDADE
from .services import remover_override_loja, resolver_configuracao, salvar_configuracao_empresa, salvar_override_loja


class DadosParametros:
    def setUp(self):
        super().setUp()
        self.usuario = get_user_model().objects.create_user("52998224725")
        self.empresa = Empresa.objects.create(
            nome="Empresa A",
            slug="a",
            cnpj="11222333000181",
        )
        self.outra = Empresa.objects.create(
            nome="Empresa B",
            slug="b",
            cnpj="11444777000161",
        )
        self.loja = Loja.objects.create(
            empresa=self.empresa,
            nome="Centro",
            cidade="Franca",
        )
        self.segunda = Loja.objects.create(
            empresa=self.empresa,
            nome="Shopping",
            cidade="Franca",
        )
        self.externa = Loja.objects.create(
            empresa=self.outra,
            nome="Outra",
            cidade="Campinas",
        )
        self.membro = MembroEmpresa.objects.create(
            usuario=self.usuario,
            empresa=self.empresa,
            papel="ADMINISTRADOR",
        )

    def request(self):
        request = RequestFactory().post("/")
        request.user = self.usuario
        request.session = {
            CONTEXTO_SESSAO: {
                "tipo_contexto": "gestao",
                "empresa_id": self.empresa.pk,
                "vinculo_id": self.membro.pk,
            },
        }
        return request

    def autenticar(self, client=None):
        client = client or self.client
        client.force_login(self.usuario)
        sessao = client.session
        sessao[CONTEXTO_SESSAO] = self.request().session[CONTEXTO_SESSAO]
        sessao.save()

    def valores(self, **mudancas):
        return dict(asdict(PADROES_FIDELIDADE), **mudancas)

    def salvar(self, **mudancas):
        return salvar_configuracao_empresa(self.request(), **self.valores(**mudancas))


class ParametrosDominioTests(DadosParametros, TestCase):
    def test_defaults_exatos_tipados_imutaveis_sem_persistencia(self):
        efetiva = resolver_configuracao(self.empresa)
        self.assertIsInstance(efetiva, ConfiguracaoEfetiva)
        self.assertEqual(
            asdict(efetiva),
            {
                "empresa_id": self.empresa.pk,
                "loja_id": None,
                "pontos_por_real": Decimal("1.00"),
                "precisao_pontos": 2,
                "modo_arredondamento_pontos": "HALF_UP",
                "validade_pontos_meses": 12,
                "resgate_minimo_pontos": 100,
                "incremento_resgate_pontos": 100,
                "valor_monetario_por_ponto": Decimal("0.05"),
                "periodo_cliente_ativo_dias": 180,
                "inatividade_suspende_beneficios_nivel": False,
                "promocao_retorno_ativa": False,
                "beneficio_primeira_compra_apos_inatividade": "SEM_BENEFICIOS_NIVEL",
                "modo_combinacao_descontos_percentuais": "ADITIVO",
                "ordem_aplicacao_resgate": "DEPOIS_DOS_DESCONTOS_PERCENTUAIS",
                "base_calculo_pontos": "BRUTO",
                "modo_aplicacao_nivel": "ANTES_DA_COMPRA",
                "bonus_pontos_retorno_percentual": Decimal("0.0000"),
                "desconto_retorno_percentual": Decimal("0.0000"),
            },
        )
        for campo in ("pontos_por_real", "valor_monetario_por_ponto"):
            self.assertIs(type(getattr(efetiva, campo)), Decimal)
        for campo in (
            "validade_pontos_meses",
            "resgate_minimo_pontos",
            "incremento_resgate_pontos",
            "periodo_cliente_ativo_dias",
        ):
            self.assertIs(type(getattr(efetiva, campo)), int)
        with self.assertRaises(FrozenInstanceError):
            efetiva.pontos_por_real = Decimal("2.00")
        self.assertFalse(ConfiguracaoFidelidadeEmpresa.objects.exists())
        self.assertFalse(OverrideFidelidadeLoja.objects.exists())
        self.assertEqual(
            resolver_configuracao(self.empresa, self.loja).pontos_por_real,
            Decimal("1.00"),
        )
        self.assertFalse(ConfiguracaoFidelidadeEmpresa.objects.exists())

    def test_primeira_edicao_cria_posterior_atualiza_sem_afetar_outra_empresa(
        self,
    ):
        config = self.salvar(pontos_por_real=Decimal("2.00"), resgate_minimo_pontos=125)
        atualizada = self.salvar(pontos_por_real=Decimal("3.00"), resgate_minimo_pontos=125)
        self.assertEqual(config.pk, atualizada.pk)
        self.assertEqual(ConfiguracaoFidelidadeEmpresa.objects.count(), 1)
        self.assertEqual(
            resolver_configuracao(self.empresa).pontos_por_real,
            Decimal("3.00"),
        )
        self.assertEqual(
            resolver_configuracao(self.empresa).resgate_minimo_pontos,
            125,
        )
        self.assertEqual(
            resolver_configuracao(self.outra).pontos_por_real,
            Decimal("1.00"),
        )

    def test_limites_invalidos_rejeitados_por_save_e_full_clean(self):
        invalidos = {
            "pontos_por_real": [Decimal("-0.01"), Decimal("NaN"), Decimal("Infinity"), None],
            "valor_monetario_por_ponto": [Decimal("0"), Decimal("-0.01"), None],
            "validade_pontos_meses": [0, -1, None],
            "resgate_minimo_pontos": [0, -1, None],
            "incremento_resgate_pontos": [0, -1, None],
            "periodo_cliente_ativo_dias": [0, -1, None],
        }
        for campo, valores in invalidos.items():
            for valor in valores:
                for metodo in ("save", "full_clean"):
                    with self.subTest(campo=campo, valor=valor, metodo=metodo), self.assertRaises(ValidationError):
                        config = ConfiguracaoFidelidadeEmpresa(
                            empresa=self.empresa,
                            **self.valores(**{campo: valor}),
                        )
                        getattr(config, metodo)()
        self.assertFalse(ConfiguracaoFidelidadeEmpresa.objects.exists())

    def test_tipos_rejeitam_float_booleano_e_fracao_inteira(self):
        for campo, valor in (
            ("pontos_por_real", 1.5),
            ("valor_monetario_por_ponto", 0.05),
            ("validade_pontos_meses", Decimal("1.5")),
            ("resgate_minimo_pontos", True),
            ("incremento_resgate_pontos", 1.5),
            ("periodo_cliente_ativo_dias", "180"),
        ):
            with self.subTest(campo=campo), self.assertRaises(ValidationError):
                self.salvar(**{campo: valor})

    def test_zero_pontos_valido_e_override_nao_aceita_null_negativo_float(
        self,
    ):
        self.salvar(pontos_por_real=Decimal("0.00"))
        self.assertEqual(
            resolver_configuracao(self.empresa).pontos_por_real,
            Decimal("0.00"),
        )
        for valor in (None, Decimal("-1"), 1.5):
            with self.subTest(valor=valor), self.assertRaises(ValidationError):
                OverrideFidelidadeLoja.objects.create(
                    loja=self.loja,
                    pontos_por_real=valor,
                )

    def test_constraints_numericas_no_banco(self):
        config = self.salvar()
        for campo in asdict(PADROES_FIDELIDADE):
            if type(getattr(PADROES_FIDELIDADE, campo)) is bool:
                continue  # BooleanField admite os dois estados; não é regra de positividade.
            invalido = {"pontos_por_real": -1, "precisao_pontos": 3,
                        "modo_arredondamento_pontos": "INVALID",
                        "bonus_pontos_retorno_percentual": -1, "desconto_retorno_percentual": 101}.get(
                campo,
                0,
            )
            with self.subTest(campo=campo), self.assertRaises(IntegrityError), transaction.atomic():
                # Bypass deliberado da validação para conferir a defesa SQL.
                ConfiguracaoFidelidadeEmpresa.objects.filter(pk=config.pk).update(
                    **{campo: invalido},
                )
        override = OverrideFidelidadeLoja.objects.create(
            loja=self.loja,
            pontos_por_real=Decimal("0"),
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            OverrideFidelidadeLoja.objects.filter(pk=override.pk).update(
                pontos_por_real=-1,
            )

    def test_relacoes_imutaveis_unicas_e_protegidas(self):
        config = self.salvar()
        override = OverrideFidelidadeLoja.objects.create(
            loja=self.loja,
            pontos_por_real=Decimal("2"),
        )
        for entidade, campo, destino in ((config, "empresa", self.outra), (override, "loja", self.segunda)):
            setattr(entidade, campo, destino)
            with self.assertRaises(ValidationError):
                entidade.save(update_fields=[campo])
            entidade.refresh_from_db()
        with self.assertRaises(ValidationError):
            ConfiguracaoFidelidadeEmpresa.objects.create(empresa=self.empresa)
        with self.assertRaises(ValidationError):
            OverrideFidelidadeLoja.objects.create(
                loja=self.loja,
                pontos_por_real=Decimal("1"),
            )
        with self.assertRaises(ProtectedError):
            self.loja.delete()
        with self.assertRaises(ProtectedError):
            self.empresa.delete()

    def test_heranca_dinamica_override_zero_e_remocao(self):
        self.salvar(pontos_por_real=Decimal("2"), validade_pontos_meses=24)
        self.assertEqual(
            resolver_configuracao(self.empresa, self.loja).pontos_por_real,
            Decimal("2"),
        )
        self.salvar(pontos_por_real=Decimal("3"), validade_pontos_meses=30)
        self.assertEqual(
            resolver_configuracao(self.empresa, self.loja).pontos_por_real,
            Decimal("3"),
        )
        override = salvar_override_loja(
            self.request(),
            self.loja.pk,
            pontos_por_real=Decimal("2"),
        )
        alterado = salvar_override_loja(
            self.request(),
            self.loja.pk,
            pontos_por_real=Decimal("0.00"),
        )
        self.assertEqual(override.pk, alterado.pk)
        self.salvar(pontos_por_real=Decimal("4"), validade_pontos_meses=36)
        efetiva = resolver_configuracao(self.empresa, self.loja)
        self.assertEqual(efetiva.pontos_por_real, Decimal("0.00"))
        self.assertEqual(efetiva.loja_id, self.loja.pk)
        corporativa = asdict(resolver_configuracao(self.empresa))
        for campo in asdict(PADROES_FIDELIDADE):
            if campo != "pontos_por_real":
                self.assertEqual(getattr(efetiva, campo), corporativa[campo])
        self.assertEqual(
            resolver_configuracao(self.empresa, self.segunda).pontos_por_real,
            Decimal("4"),
        )
        remover_override_loja(self.request(), self.loja.pk)
        self.assertFalse(OverrideFidelidadeLoja.objects.exists())
        self.assertEqual(
            resolver_configuracao(self.empresa, self.loja).pontos_por_real,
            Decimal("4"),
        )

    def test_override_sem_corporativa_nao_copia_defaults(self):
        salvar_override_loja(
            self.request(),
            self.loja.pk,
            pontos_por_real=Decimal("5"),
        )
        efetiva = resolver_configuracao(self.empresa, self.loja)
        self.assertEqual(efetiva.pontos_por_real, Decimal("5"))
        self.assertEqual(efetiva.validade_pontos_meses, 12)
        self.assertFalse(ConfiguracaoFidelidadeEmpresa.objects.exists())

    def test_cross_tenant_rejeitado_na_resolucao_e_escrita(self):
        with self.assertRaises(ValidationError):
            resolver_configuracao(self.empresa, self.externa)
        self.externa.empresa_id = self.empresa.pk
        with self.assertRaises(ValidationError):
            resolver_configuracao(self.empresa, self.externa)
        with self.assertRaises(PermissionDenied):
            salvar_override_loja(
                self.request(),
                self.externa.pk,
                pontos_por_real=Decimal("2"),
            )
        with self.assertRaises(PermissionDenied):
            remover_override_loja(self.request(), self.externa.pk)

    def test_services_revalidam_gestor_e_membro_inativo(self):
        for papel, ativo in (("GESTOR", True), ("ADMINISTRADOR", False)):
            self.membro.papel, self.membro.ativo = papel, ativo
            self.membro.save()
            with self.assertRaises(PermissionDenied):
                self.salvar()
            with self.assertRaises(PermissionDenied):
                salvar_override_loja(
                    self.request(),
                    self.loja.pk,
                    pontos_por_real=Decimal("2"),
                )
            with self.assertRaises(PermissionDenied):
                remover_override_loja(self.request(), self.loja.pk)
        self.assertFalse(ConfiguracaoFidelidadeEmpresa.objects.exists())
        self.assertFalse(OverrideFidelidadeLoja.objects.exists())


class ParametrosHTTPTests(DadosParametros, TestCase):
    def urls(self):
        return [
            reverse("empresas:configuracao_empresa"),
            reverse("empresas:configuracao_loja", args=[self.loja.pk]),
            reverse("empresas:remover_override_loja", args=[self.loja.pk]),
        ]

    def test_form_defaults_primeira_edicao_posterior_e_empresa_do_contexto(
        self,
    ):
        self.autenticar()
        url = self.urls()[0]
        resposta = self.client.get(url)
        for campo, valor in self.valores().items():
            self.assertEqual(resposta.context["form"].initial[campo], valor)
        self.assertFalse(ConfiguracaoFidelidadeEmpresa.objects.exists())
        self.assertEqual(
            self.client.post(url, dict(self.valores(), empresa_id=self.outra.pk)).status_code,
            302,
        )
        config = ConfiguracaoFidelidadeEmpresa.objects.get()
        self.assertEqual(config.empresa_id, self.empresa.pk)
        self.assertEqual(
            self.client.post(url, self.valores(pontos_por_real="2.50")).status_code,
            302,
        )
        config.refresh_from_db()
        self.assertEqual(config.pontos_por_real, Decimal("2.50"))
        self.assertEqual(ConfiguracaoFidelidadeEmpresa.objects.count(), 1)
        self.assertTrue(
            self.client.post(url, self.valores(validade_pontos_meses=0)).context["form"].errors,
        )

    def test_politicas_beneficios_persistem_pelas_secoes_existentes(self):
        self.autenticar()
        dados = self.valores(
            modo_aplicacao_nivel='ATINGIDO_NA_COMPRA',
            base_calculo_pontos='LIQUIDO',
            inatividade_suspende_beneficios_nivel=True,
            beneficio_primeira_compra_apos_inatividade='COM_BENEFICIOS_NIVEL',
            promocao_retorno_ativa=True,
            bonus_pontos_retorno_percentual='30.1250',
            desconto_retorno_percentual='10.0000',
            modo_combinacao_descontos_percentuais='SEQUENCIAL',
            ordem_aplicacao_resgate='ANTES_DOS_DESCONTOS_PERCENTUAIS',
        )
        self.assertEqual(
            self.client.post(self.urls()[0], dados).status_code,
            302,
        )
        cfg = ConfiguracaoFidelidadeEmpresa.objects.get(empresa=self.empresa)
        for campo, valor in dados.items():
            if campo in ('bonus_pontos_retorno_percentual', 'desconto_retorno_percentual'):
                valor = Decimal(valor)
            self.assertEqual(getattr(cfg, campo), valor)
        resposta = self.client.post(
            self.urls()[0],
            dict(dados, desconto_retorno_percentual='101'),
        )
        self.assertIn(
            'desconto_retorno_percentual',
            resposta.context['form'].errors,
        )
        cfg.refresh_from_db()
        self.assertEqual(cfg.desconto_retorno_percentual, Decimal('10'))

    def test_loja_exibe_origem_altera_remove_e_nao_cria_linha_null(self):
        self.autenticar()
        url = self.urls()[1]
        self.assertContains(self.client.get(url), "Origem: Empresa")
        self.assertFalse(OverrideFidelidadeLoja.objects.exists())
        self.assertEqual(
            self.client.post(url, {"pontos_por_real": "0.00"}).status_code,
            302,
        )
        self.assertContains(
            self.client.get(url),
            "Origem: Configuração específica da Loja",
        )
        self.assertEqual(
            OverrideFidelidadeLoja.objects.get().pontos_por_real,
            Decimal("0"),
        )
        self.assertTrue(
            self.client.post(url, {"pontos_por_real": ""}).context["form"].errors,
        )
        self.assertEqual(self.client.post(self.urls()[2]).status_code, 302)
        self.assertFalse(OverrideFidelidadeLoja.objects.exists())
        self.assertContains(self.client.get(url), "Origem: Empresa")

    def test_post_url_e_id_adulterados_rejeitados(self):
        self.autenticar()
        for rota in ("configuracao_loja", "remover_override_loja"):
            url = reverse(f"empresas:{rota}", args=[self.externa.pk])
            self.assertEqual(
                self.client.post(url, {"pontos_por_real": "2"}).status_code,
                403,
            )
            url = reverse(f"empresas:{rota}", args=[self.loja.pk])
            self.assertEqual(
                self.client.post(url, {"loja_id": self.externa.pk, "pontos_por_real": "2"}).status_code,
                403,
            )
        self.assertFalse(OverrideFidelidadeLoja.objects.exists())

    def test_login_contexto_gestor_inativo_e_cliente(self):
        for url in self.urls():
            self.assertEqual(
                self.client.post(url, self.valores()).status_code,
                302,
            )
        for papel, ativo in (("GESTOR", True), ("ADMINISTRADOR", False)):
            self.membro.papel, self.membro.ativo = papel, ativo
            self.membro.save()
            for url in self.urls():
                self.autenticar()
                self.assertEqual(
                    self.client.post(url, self.valores()).status_code,
                    403,
                )
            for url in self.urls()[:2]:
                self.autenticar()
                self.assertEqual(self.client.get(url).status_code, 403)
        self.membro.papel, self.membro.ativo = "ADMINISTRADOR", True
        self.membro.save()
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.get(self.urls()[0]).status_code, 403)
        cliente = Cliente.objects.create(usuario=self.usuario, empresa=self.empresa)
        sessao = self.client.session
        sessao[CONTEXTO_SESSAO] = {
            "tipo_contexto": "cliente",
            "empresa_id": self.empresa.pk,
            "vinculo_id": cliente.pk,
        }
        sessao.save()
        self.assertEqual(
            self.client.post(self.urls()[0], self.valores()).status_code,
            403,
        )

    def test_remocao_post_csrf_e_escritas_protegidas(self):
        navegador = Client(enforce_csrf_checks=True)
        self.autenticar(navegador)
        salvar_override_loja(
            self.request(),
            self.loja.pk,
            pontos_por_real=Decimal("2"),
        )
        for url in self.urls():
            self.assertEqual(
                navegador.post(url, self.valores()).status_code,
                403,
            )
        self.assertEqual(navegador.get(self.urls()[2]).status_code, 405)
        navegador.get(self.urls()[1])
        self.assertEqual(
            navegador.post(self.urls()[2], {"csrfmiddlewaretoken": navegador.cookies["csrftoken"].value}).status_code,
            302,
        )
        self.assertFalse(OverrideFidelidadeLoja.objects.exists())

    def test_area_gestao_exibe_controles_somente_admin(self):
        self.autenticar()
        resposta = self.client.get(reverse("empresas:area"))
        self.assertContains(resposta, self.urls()[0])
        self.assertContains(resposta, self.urls()[1])
        self.membro.papel = "GESTOR"
        self.membro.save()
        resposta = self.client.get(reverse("empresas:area"))
        self.assertNotContains(resposta, self.urls()[0])
        self.assertNotContains(resposta, self.urls()[1])


class PoliticaPontosTests(DadosParametros, TestCase):
    def test_choices_persistidas_com_resolucao_corporativa_e_override_apenas_da_taxa(
        self,
    ):
        from .forms import OverrideFidelidadeLojaForm

        salvar_override_loja(
            self.request(),
            self.loja.pk,
            pontos_por_real=Decimal('1.25'),
        )
        for precisao in (0, 1, 2, 4):
            for modo in ('HALF_UP', 'DOWN', 'UP'):
                self.salvar(
                    precisao_pontos=precisao,
                    modo_arredondamento_pontos=modo,
                )
                efetiva = resolver_configuracao(self.empresa, self.loja)
                self.assertEqual(
                    (
                        efetiva.precisao_pontos,
                        efetiva.modo_arredondamento_pontos,
                    ),
                    (precisao, modo),
                )
                self.assertEqual(efetiva.pontos_por_real, Decimal('1.25'))
                outra = resolver_configuracao(self.outra)
                self.assertEqual(
                    (outra.precisao_pontos, outra.modo_arredondamento_pontos),
                    (2, 'HALF_UP'),
                )
        self.assertEqual(
            set(OverrideFidelidadeLojaForm().fields),
            {'pontos_por_real'},
        )
        self.assertNotIn(
            'precisao_pontos',
            {f.name for f in OverrideFidelidadeLoja._meta.fields},
        )
        self.assertNotIn(
            'modo_arredondamento_pontos',
            {f.name for f in OverrideFidelidadeLoja._meta.fields},
        )

    def test_choices_invalidas_rejeitadas_no_model_e_service(self):
        for campo, valores in {
            'precisao_pontos': (-1, 3, 5, True, '2', Decimal('2'), None),
            'modo_arredondamento_pontos': ('half_up', 'HALF_EVEN', '', None, 1),
        }.items():
            for valor in valores:
                for metodo in ('full_clean', 'save', 'service'):
                    with self.subTest(campo=campo, valor=valor, metodo=metodo), self.assertRaises(ValidationError):
                        if metodo == 'service':
                            self.salvar(**{campo: valor})
                        else:
                            config = ConfiguracaoFidelidadeEmpresa(
                                empresa=self.empresa,
                                **self.valores(**{campo: valor}),
                            )
                            getattr(config, metodo)()
        self.assertFalse(ConfiguracaoFidelidadeEmpresa.objects.exists())

    def test_form_admin_persiste_politica_e_post_loja_nao_sobrescreve(self):
        self.autenticar()
        url = reverse('empresas:configuracao_empresa')
        resposta = self.client.get(url)
        for campo in ('precisao_pontos', 'modo_arredondamento_pontos'):
            self.assertIn(campo, resposta.context['form'].fields)
        resposta = self.client.post(
            url,
            self.valores(precisao_pontos=0, modo_arredondamento_pontos='DOWN'),
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(
            resolver_configuracao(self.empresa).precisao_pontos,
            0,
        )
        self.assertEqual(
            resolver_configuracao(self.empresa).modo_arredondamento_pontos,
            'DOWN',
        )
        resposta = self.client.post(
            reverse('empresas:configuracao_loja', args=[self.loja.pk]),
            {
                'pontos_por_real': '1.25',
                'precisao_pontos': 4,
                'modo_arredondamento_pontos': 'UP',
            },
        )
        self.assertEqual(resposta.status_code, 302)
        efetiva = resolver_configuracao(self.empresa, self.loja)
        self.assertEqual(
            (efetiva.precisao_pontos, efetiva.modo_arredondamento_pontos),
            (0, 'DOWN'),
        )
        for mudanca in ({'precisao_pontos': 3}, {'modo_arredondamento_pontos': 'HALF_EVEN'}):
            resposta = self.client.post(url, self.valores(**mudanca))
            self.assertTrue(resposta.context['form'].errors)
