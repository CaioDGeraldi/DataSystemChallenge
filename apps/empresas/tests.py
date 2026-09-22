from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from .models import AcessoLoja, Empresa, MembroEmpresa, Loja
from .validators import validar_cnpj


class EmpresaTests(TestCase):
    def test_loja_nao_pode_trocar_empresa_apos_criacao(self):
        empresa = Empresa.objects.create(nome="Empresa A", cnpj="11222333000181")
        outra_empresa = Empresa.objects.create(nome="Empresa B", cnpj="11444777000161")
        loja = Loja.objects.create(empresa=empresa, nome="Centro", cidade="Franca")
        loja.nome = "Centro Novo"
        loja.save(update_fields=["nome"])
        for parcial in (False, True):
            with self.subTest(parcial=parcial):
                loja.empresa_id = outra_empresa.pk
                with self.assertRaises(ValidationError):
                    loja.clean()
                with self.assertRaises(ValidationError):
                    loja.save(**({"update_fields": ["empresa"]} if parcial else {}))
                loja.refresh_from_db()
                self.assertEqual(loja.empresa_id, empresa.pk)
                self.assertEqual(loja.nome, "Centro Novo")

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


class MembroEmpresaTests(TestCase):
    def test_membro_nao_pode_trocar_empresa_apos_criacao(self):
        outra_empresa = Empresa.objects.create(nome="Empresa B", cnpj="11444777000161")
        membro = MembroEmpresa.objects.create(
            usuario=self.usuario, empresa=self.empresa, papel=MembroEmpresa.Papel.GESTOR
        )
        membro.ativo = False
        membro.save(update_fields=["ativo"])
        for parcial in (False, True):
            with self.subTest(parcial=parcial):
                membro.empresa = outra_empresa
                with self.assertRaises(ValidationError):
                    membro.clean()
                with self.assertRaises(ValidationError):
                    membro.save(**({"update_fields": ["empresa"]} if parcial else {}))
                membro.refresh_from_db()
                self.assertEqual(membro.empresa_id, self.empresa.pk)
                self.assertFalse(membro.ativo)

    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nome="Empresa A", cnpj="11222333000181")
        cls.usuario = get_user_model().objects.create_user("52998224725")

    def test_empresa_com_varios_gestores_ligados_aos_usuarios(self):
        outro_usuario = get_user_model().objects.create_user("11144477735")
        gestor = MembroEmpresa.objects.create(usuario=self.usuario, empresa=self.empresa, papel=MembroEmpresa.Papel.GESTOR)
        outro_gestor = MembroEmpresa.objects.create(usuario=outro_usuario, empresa=self.empresa, papel=MembroEmpresa.Papel.GESTOR)
        self.assertCountEqual(self.empresa.membros.all(), [gestor, outro_gestor])
        self.assertIn(gestor, self.usuario.membros_empresas.all())
        self.assertEqual(gestor.usuario, self.usuario)

    def test_usuario_pode_ser_membro_de_empresas_distintas(self):
        outra_empresa = Empresa.objects.create(nome="Empresa B", cnpj="11444777000161")
        MembroEmpresa.objects.create(usuario=self.usuario, empresa=self.empresa, papel=MembroEmpresa.Papel.GESTOR)
        MembroEmpresa.objects.create(usuario=self.usuario, empresa=outra_empresa, papel=MembroEmpresa.Papel.ADMINISTRADOR)
        self.assertEqual(self.usuario.membros_empresas.count(), 2)

    def test_gestor_protege_usuario_e_empresa_contra_exclusao(self):
        MembroEmpresa.objects.create(usuario=self.usuario, empresa=self.empresa, papel=MembroEmpresa.Papel.GESTOR)
        for entidade in (self.usuario, self.empresa):
            with self.subTest(entidade=type(entidade).__name__), self.assertRaises(ProtectedError):
                entidade.delete()

    def test_nao_duplica_membro_na_mesma_empresa(self):
        MembroEmpresa.objects.create(usuario=self.usuario, empresa=self.empresa, papel=MembroEmpresa.Papel.GESTOR)
        with self.assertRaises(ValidationError):
            MembroEmpresa.objects.create(usuario=self.usuario, empresa=self.empresa, papel=MembroEmpresa.Papel.ADMINISTRADOR)
        with self.assertRaises(IntegrityError), transaction.atomic():
            MembroEmpresa.objects.bulk_create([
                MembroEmpresa(usuario=self.usuario, empresa=self.empresa, papel=MembroEmpresa.Papel.GESTOR)
            ])

    def test_papel_explicito_e_valido_obrigatorio(self):
        for papel in ("", "OUTRO", None):
            with self.subTest(papel=papel), self.assertRaises(ValidationError):
                MembroEmpresa.objects.create(usuario=self.usuario, empresa=self.empresa, papel=papel)
        with self.assertRaises(ValidationError):
            MembroEmpresa.objects.create(usuario=self.usuario, empresa=self.empresa)

    def test_administrador_ativo_sem_vinculos_por_loja(self):
        membro = MembroEmpresa.objects.create(
            usuario=self.usuario, empresa=self.empresa, papel=MembroEmpresa.Papel.ADMINISTRADOR
        )
        Loja.objects.create(empresa=self.empresa, nome="Nova Loja", cidade="Franca")
        membro.refresh_from_db()
        self.assertTrue(membro.ativo)
        self.assertEqual(membro.papel, MembroEmpresa.Papel.ADMINISTRADOR)
        self.assertFalse(membro.acessos_lojas.exists())
        membro.ativo = False
        membro.save()
        membro.refresh_from_db()
        self.assertFalse(membro.ativo)


class AcessoLojaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nome="Empresa A", cnpj="11222333000181")
        cls.outra_empresa = Empresa.objects.create(nome="Empresa B", cnpj="11444777000161")
        cls.usuario = get_user_model().objects.create_user("52998224725")
        cls.membro = MembroEmpresa.objects.create(
            usuario=cls.usuario, empresa=cls.empresa, papel=MembroEmpresa.Papel.GESTOR
        )
        cls.loja = Loja.objects.create(empresa=cls.empresa, nome="Centro", cidade="Franca")
        cls.outra_loja = Loja.objects.create(empresa=cls.outra_empresa, nome="Centro", cidade="Franca")

    def test_gestor_com_acesso_a_varias_lojas_da_empresa(self):
        segunda_loja = Loja.objects.create(empresa=self.empresa, nome="Shopping", cidade="Franca")
        for loja in (self.loja, segunda_loja):
            AcessoLoja.objects.create(membro=self.membro, loja=loja)
        self.assertCountEqual(self.membro.acessos_lojas.values_list("loja_id", flat=True), [self.loja.pk, segunda_loja.pk])

    def test_rejeita_acesso_duplicado_no_model_e_banco(self):
        AcessoLoja.objects.create(membro=self.membro, loja=self.loja)
        with self.assertRaises(ValidationError):
            AcessoLoja.objects.create(membro=self.membro, loja=self.loja)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AcessoLoja.objects.bulk_create([AcessoLoja(membro=self.membro, loja=self.loja)])

    def test_clean_e_create_rejeitam_cross_tenant(self):
        with self.assertRaises(ValidationError):
            AcessoLoja(membro=self.membro, loja=self.outra_loja).clean()
        with self.assertRaises(ValidationError):
            AcessoLoja.objects.create(membro_id=self.membro.pk, loja_id=self.outra_loja.pk)
        self.assertFalse(AcessoLoja.objects.exists())

    def test_save_rejeita_alteracao_cross_tenant(self):
        acesso = AcessoLoja.objects.create(membro=self.membro, loja=self.loja)
        acesso.loja = self.outra_loja
        with self.assertRaises(ValidationError):
            acesso.save(update_fields=["loja"])
        acesso.refresh_from_db()
        self.assertEqual(acesso.loja_id, self.loja.pk)

    def test_acesso_protege_membro_e_loja(self):
        AcessoLoja.objects.create(membro=self.membro, loja=self.loja)
        for entidade in (self.membro, self.loja):
            with self.subTest(entidade=type(entidade).__name__), self.assertRaises(ProtectedError):
                entidade.delete()
