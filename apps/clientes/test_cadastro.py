from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connections
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from apps.empresas.models import Empresa, MembroEmpresa

from .models import Cliente
from .services import cadastrar_cliente


SENHA = "Fortaleza!9042"


class CadastroTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nome="Empresa A", slug="empresa-a", cnpj="11222333000181")
        cls.outra = Empresa.objects.create(nome="Empresa B", slug="empresa-b", cnpj="11444777000161")

    def dados(self, **alteracoes):
        return dict({"cpf": "529.982.247-25", "first_name": "Ana", "last_name": "Silva",
                     "senha": SENHA, "confirmacao": SENHA}, **alteracoes)

    def cadastrar(self, empresa=None, **dados):
        return self.client.post(reverse("clientes:cadastro", args=[(empresa or self.empresa).slug]), self.dados(**dados))

    def usuario_existente(self, **extra):
        return get_user_model().objects.create_user("52998224725", SENHA, first_name="Original", last_name="Pessoa", **extra)

    def test_empresa_inexistente_404_sem_escritas(self):
        resposta = self.client.post("/empresa/inexistente/cadastro/", self.dados())
        self.assertEqual(resposta.status_code, 404)
        self.assertFalse(get_user_model().objects.exists())
        self.assertFalse(Cliente.objects.exists())

    def test_cpf_novo_cria_identidade_e_vinculo_na_empresa_da_url(self):
        resposta = self.cadastrar()
        self.assertRedirects(resposta, reverse("usuarios:login"))
        usuario = get_user_model().objects.get()
        cliente = Cliente.objects.get()
        self.assertEqual(usuario.cpf, "52998224725")
        self.assertEqual((usuario.first_name, usuario.last_name), ("Ana", "Silva"))
        self.assertTrue(usuario.check_password(SENHA))
        self.assertEqual((cliente.usuario_id, cliente.empresa_id), (usuario.pk, self.empresa.pk))
        self.assertFalse(MembroEmpresa.objects.exists())

    def test_cadastro_novo_rejeita_senhas_divergentes_fracas_e_nomes_ausentes(self):
        for dados in ({"confirmacao": "diferente"}, {"senha": "123", "confirmacao": "123"},
                      {"first_name": ""}, {"last_name": ""}, {"cpf": "abc"}):
            with self.subTest(dados=dados):
                resposta = self.cadastrar(**dados)
                self.assertEqual(resposta.status_code, 200)
                self.assertTrue(resposta.context["form"].errors)
                self.assertFalse(get_user_model().objects.exists())
                self.assertFalse(Cliente.objects.exists())

    def test_password_validators_configurados_sao_aplicados(self):
        with self.settings(AUTH_PASSWORD_VALIDATORS=[{
            "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 30}
        }]):
            self.assertTrue(self.cadastrar().context["form"].errors)
        self.assertFalse(get_user_model().objects.exists())

    def test_operacao_atomica_desfaz_usuario_se_vinculo_falhar(self):
        with patch("apps.clientes.services.Cliente.objects.get_or_create", side_effect=IntegrityError("falha simulada")):
            with self.assertRaises(IntegrityError):
                cadastrar_cliente(empresa=self.empresa, **self.dados())
        self.assertFalse(get_user_model().objects.exists())
        self.assertFalse(Cliente.objects.exists())

    def test_identidade_existente_aderindo_segunda_empresa_preserva_dados(self):
        usuario = self.usuario_existente()
        senha_hash = usuario.password
        Cliente.objects.create(usuario=usuario, empresa=self.empresa)
        resposta = self.cadastrar(self.outra, first_name="Outro", last_name="Nome")
        self.assertEqual(resposta.status_code, 302)
        usuario.refresh_from_db()
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(Cliente.objects.count(), 2)
        self.assertEqual((usuario.cpf, usuario.first_name, usuario.last_name, usuario.password),
                         ("52998224725", "Original", "Pessoa", senha_hash))

    def test_existente_nao_exige_nomes_e_nao_duplica_cliente(self):
        self.usuario_existente()
        for _ in range(2):
            self.assertEqual(self.cadastrar(first_name="", last_name="").status_code, 302)
        self.assertEqual(Cliente.objects.count(), 1)
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_senha_errada_nao_cria_vinculo(self):
        self.usuario_existente()
        resposta = self.cadastrar(senha="Incorreta!9042", confirmacao="Incorreta!9042")
        self.assertTrue(resposta.context["form"].errors)
        self.assertFalse(Cliente.objects.exists())

    def test_usuario_inativo_nao_cria_vinculo(self):
        self.usuario_existente(is_active=False)
        self.assertTrue(self.cadastrar().context["form"].errors)
        self.assertFalse(Cliente.objects.exists())

    def test_senha_existente_nao_e_submetida_a_nova_politica(self):
        self.usuario_existente()
        with self.settings(AUTH_PASSWORD_VALIDATORS=[{
            "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 100}
        }]):
            self.assertEqual(self.cadastrar(first_name="", last_name="").status_code, 302)
        self.assertEqual(Cliente.objects.count(), 1)

    def test_empresa_enviada_no_post_nao_substitui_slug(self):
        dados = self.dados()
        dados["empresa_id"] = self.outra.pk
        self.client.post(reverse("clientes:cadastro", args=[self.empresa.slug]), dados)
        self.assertEqual(Cliente.objects.get().empresa_id, self.empresa.pk)


class ConcorrenciaCadastroTests(TransactionTestCase):
    def disputar_cadastro(self, senhas):
        empresa = Empresa.objects.create(nome="Empresa A", slug="empresa-a", cnpj="11222333000181")
        manager = type(get_user_model().objects)
        original = manager.create_user
        barreira = Barrier(2)

        def disputar_criacao(self, *args, **kwargs):
            barreira.wait(timeout=15)
            return original(self, *args, **kwargs)

        def executar(senha):
            close_old_connections()
            try:
                cliente = cadastrar_cliente(empresa=empresa, cpf="52998224725", senha=senha,
                                             confirmacao=senha, first_name="Ana", last_name="Silva")
                return cliente.pk
            except ValidationError:
                return None
            finally:
                connections.close_all()

        with patch.object(manager, "create_user", disputar_criacao), ThreadPoolExecutor(max_workers=2) as pool:
            futuros = [pool.submit(executar, senha) for senha in senhas]
            return [f.result(timeout=30) for f in futuros]

    def test_duas_criacoes_simultaneas_do_mesmo_cpf_preservam_identidade_e_vinculo(self):
        ids = self.disputar_cadastro([SENHA, SENHA])
        self.assertIsNotNone(ids[0])
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(Cliente.objects.count(), 1)

    def test_disputa_de_cpf_exige_senha_da_identidade_vencedora(self):
        senhas = [SENHA, "OutraFortaleza!9042"]
        ids = self.disputar_cadastro(senhas)
        self.assertEqual(ids.count(None), 1)
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(Cliente.objects.count(), 1)
        usuario = get_user_model().objects.get()
        for senha, resultado in zip(senhas, ids):
            self.assertEqual(usuario.check_password(senha), resultado is not None)
