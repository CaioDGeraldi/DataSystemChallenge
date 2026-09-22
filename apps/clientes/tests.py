from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from apps.empresas.models import Empresa, MembroEmpresa

from .models import Cliente


class ClienteTests(TestCase):
    def test_cliente_nao_pode_trocar_empresa_apos_criacao(self):
        outra_empresa = Empresa.objects.create(nome="Empresa B", cnpj="11444777000161")
        cliente = Cliente.objects.create(usuario=self.usuario, empresa=self.empresa)
        cliente.save()
        for parcial in (False, True):
            with self.subTest(parcial=parcial):
                cliente.empresa = outra_empresa
                with self.assertRaises(ValidationError):
                    cliente.clean()
                with self.assertRaises(ValidationError):
                    cliente.save(**({"update_fields": ["empresa"]} if parcial else {}))
                cliente.refresh_from_db()
                self.assertEqual(cliente.empresa_id, self.empresa.pk)

    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nome="Empresa A", cnpj="11222333000181")
        cls.usuario = get_user_model().objects.create_user(
            "52998224725", first_name="Ana", last_name="Silva"
        )

    def test_empresa_com_varios_clientes_ligados_aos_usuarios(self):
        outro_usuario = get_user_model().objects.create_user("11144477735")
        cliente = Cliente.objects.create(usuario=self.usuario, empresa=self.empresa)
        outro_cliente = Cliente.objects.create(usuario=outro_usuario, empresa=self.empresa)
        self.assertCountEqual(self.empresa.clientes.all(), [cliente, outro_cliente])
        self.assertIn(cliente, self.usuario.clientes.all())
        self.assertEqual(cliente.usuario, self.usuario)
        self.assertIsNotNone(cliente.cadastrado_em)

    def test_mesmo_usuario_pode_ser_cliente_e_gestor(self):
        cliente = Cliente.objects.create(usuario=self.usuario, empresa=self.empresa)
        gestor = MembroEmpresa.objects.create(usuario=self.usuario, empresa=self.empresa, papel=MembroEmpresa.Papel.GESTOR)
        self.assertEqual(cliente.usuario_id, gestor.usuario_id)
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(cliente.usuario.get_full_name(), "Ana Silva")
        self.assertEqual(gestor.usuario.cpf, "52998224725")

    def test_usuario_pode_ter_clientes_em_empresas_distintas(self):
        outra_empresa = Empresa.objects.create(nome="Empresa B", cnpj="11444777000161")
        Cliente.objects.create(usuario=self.usuario, empresa=self.empresa)
        Cliente.objects.create(usuario=self.usuario, empresa=outra_empresa)
        self.assertEqual(self.usuario.clientes.count(), 2)

    def test_usuario_nao_pode_duplicar_cliente_na_mesma_empresa(self):
        Cliente.objects.create(usuario=self.usuario, empresa=self.empresa)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Cliente.objects.create(usuario=self.usuario, empresa=self.empresa)

    def test_cliente_protege_usuario_e_empresa_contra_exclusao(self):
        Cliente.objects.create(usuario=self.usuario, empresa=self.empresa)
        for entidade in (self.usuario, self.empresa):
            with self.subTest(entidade=type(entidade).__name__), self.assertRaises(ProtectedError):
                entidade.delete()
