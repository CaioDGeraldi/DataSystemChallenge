from django.contrib.auth import authenticate, get_user_model
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.test import TestCase

from .validators import validar_cpf


Usuario = get_user_model()


class UsuarioTests(TestCase):
    def test_cria_usuario_com_cpf_valido_e_senha_hash(self):
        usuario = Usuario.objects.create_user(
            cpf="52998224725",
            password="senha-segura-123",
            first_name="Ana",
            last_name="Silva",
        )

        self.assertEqual(usuario.cpf, "52998224725")
        self.assertEqual(usuario.first_name, "Ana")
        self.assertEqual(usuario.last_name, "Silva")
        self.assertNotEqual(usuario.password, "senha-segura-123")
        self.assertTrue(usuario.check_password("senha-segura-123"))

    def test_normaliza_cpf_com_mascara(self):
        usuario = Usuario.objects.create_user(" 529.982.247-25 \t", "senha-segura-123")

        self.assertEqual(usuario.cpf, "52998224725")
        self.assertEqual(Usuario.objects.get(pk=usuario.pk).cpf, "52998224725")

    def test_normaliza_whitespace_em_cpf_sem_mascara(self):
        usuario = Usuario.objects.create_user(" 529 982 247 25 ", "senha-segura-123")

        self.assertEqual(usuario.cpf, "52998224725")

    def test_validador_aceita_cpf_mascarado(self):
        self.assertIsNone(validar_cpf(" 529.982.247-25 "))

    def test_rejeita_cpf_invalido(self):
        for cpf in ("111.111.111-11", "529.982.247-26", "123", "", None, 52998224725):
            with self.subTest(cpf=cpf), self.assertRaises(ValidationError):
                Usuario.objects.create_user(cpf, "senha-segura-123")

    def test_rejeita_letras_e_caracteres_arbitrarios(self):
        for cpf in ("529a98224725", "529/982/247-25", "529.982.247_25", "529..982.247-25"):
            with self.subTest(cpf=cpf), self.assertRaises(ValidationError):
                Usuario.objects.create_user(cpf, "senha-segura-123")
            with self.subTest(cpf=cpf), self.assertRaises(ValidationError):
                validar_cpf(cpf)

    def test_cpf_unico_apos_normalizacao(self):
        Usuario.objects.create_user("52998224725", "senha-segura-123")

        with self.assertRaises(ValidationError):
            Usuario.objects.create_user("529.982.247-25", "outra-senha-123")

    def test_autentica_usando_cpf(self):
        usuario = Usuario.objects.create_user("52998224725", "senha-segura-123")

        autenticado = authenticate(cpf="52998224725", password="senha-segura-123")

        self.assertEqual(autenticado, usuario)
        self.assertIsNone(authenticate(cpf="52998224725", password="incorreta"))

    def test_autentica_usando_cpf_mascarado(self):
        usuario = Usuario.objects.create_user("52998224725", "senha-segura-123")

        autenticado = authenticate(cpf=" 529.982.247-25 ", password="senha-segura-123")

        self.assertEqual(autenticado, usuario)

    def test_cpf_malformado_falha_autenticacao_sem_excecao(self):
        Usuario.objects.create_user("52998224725", "senha-segura-123")

        for cpf in ("abc", "529/982/247-25"):
            with self.subTest(cpf=cpf):
                self.assertIsNone(authenticate(cpf=cpf, password="senha-segura-123"))

    def test_cria_superusuario_sem_username(self):
        usuario = Usuario.objects.create_superuser(
            cpf="11144477735",
            password="senha-segura-123",
            first_name="Admin",
            last_name="Sistema",
        )

        self.assertTrue(usuario.is_staff)
        self.assertTrue(usuario.is_superuser)
        with self.assertRaises(FieldDoesNotExist):
            Usuario._meta.get_field("username")
        self.assertEqual(Usuario.USERNAME_FIELD, "cpf")
