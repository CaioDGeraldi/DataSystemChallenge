from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from .models import Empresa, Gestor, Loja
from .validators import validar_cnpj


class EmpresaTests(TestCase):
    def test_cria_empresa_com_cnpj_valido(self):
        empresa = Empresa.objects.create(nome="Empresa A", cnpj="11222333000181")
        empresa.refresh_from_db()
        self.assertEqual(empresa.cnpj, "11222333000181")
        self.assertIsNotNone(empresa.criado_em)

    def test_normaliza_mascara_e_whitespace(self):
        empresa = Empresa.objects.create(nome="Empresa A", cnpj=" \t11.222.333/0001-81\n")
        empresa.refresh_from_db()
        self.assertEqual(empresa.cnpj, "11222333000181")

    def test_valida_cnpj_canonico_e_mascarado(self):
        for cnpj in ("11222333000181", "11.222.333/0001-81", " 11 222 333 0001 81 "):
            with self.subTest(cnpj=cnpj):
                validar_cnpj(cnpj)

    def test_rejeita_digitos_verificadores_invalidos(self):
        for cnpj in ("11222333000191", "11222333000182", "00000000000000"):
            with self.subTest(cnpj=cnpj), self.assertRaises(ValidationError):
                Empresa.objects.create(nome="Empresa A", cnpj=cnpj)

    def test_rejeita_formato_invalido_sem_descartar_caracteres(self):
        for cnpj in (
            "abc11222333000181", "11/222/333/0001-81", "11.222.333/0001_81",
            "１１２２２３３３０００１８１", "123", "", None, 11222333000181,
        ):
            with self.subTest(cnpj=cnpj), self.assertRaises(ValidationError):
                Empresa.objects.create(nome="Empresa A", cnpj=cnpj)
            with self.subTest(validador=cnpj), self.assertRaises(ValidationError):
                validar_cnpj(cnpj)

    def test_cnpj_unico_apos_normalizacao(self):
        Empresa.objects.create(nome="Empresa A", cnpj="11222333000181")
        with self.assertRaises(ValidationError):
            Empresa.objects.create(nome="Empresa B", cnpj="11.222.333/0001-81")

    def test_empresa_com_varias_lojas(self):
        empresa = Empresa.objects.create(nome="Empresa A", cnpj="11222333000181")
        loja_a = Loja.objects.create(empresa=empresa, nome="Centro", cidade="Franca")
        loja_b = Loja.objects.create(empresa=empresa, nome="Shopping", cidade="Franca")
        self.assertCountEqual(empresa.lojas.all(), [loja_a, loja_b])

    def test_loja_protege_empresa_contra_exclusao(self):
        empresa = Empresa.objects.create(nome="Empresa A", cnpj="11222333000181")
        Loja.objects.create(empresa=empresa, nome="Centro", cidade="Franca")
        with self.assertRaises(ProtectedError):
            empresa.delete()


class GestorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nome="Empresa A", cnpj="11222333000181")
        cls.usuario = get_user_model().objects.create_user("52998224725")

    def test_empresa_com_varios_gestores_ligados_aos_usuarios(self):
        outro_usuario = get_user_model().objects.create_user("11144477735")
        gestor = Gestor.objects.create(usuario=self.usuario, empresa=self.empresa)
        outro_gestor = Gestor.objects.create(usuario=outro_usuario, empresa=self.empresa)
        self.assertCountEqual(self.empresa.gestores.all(), [gestor, outro_gestor])
        self.assertEqual(self.usuario.gestor, gestor)
        self.assertEqual(gestor.usuario, self.usuario)

    def test_usuario_nao_pode_ter_segundo_gestor_em_outra_empresa(self):
        outra_empresa = Empresa.objects.create(nome="Empresa B", cnpj="11444777000161")
        Gestor.objects.create(usuario=self.usuario, empresa=self.empresa)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Gestor.objects.create(usuario=self.usuario, empresa=outra_empresa)

    def test_gestor_protege_usuario_e_empresa_contra_exclusao(self):
        Gestor.objects.create(usuario=self.usuario, empresa=self.empresa)
        for entidade in (self.usuario, self.empresa):
            with self.subTest(entidade=type(entidade).__name__), self.assertRaises(ProtectedError):
                entidade.delete()
