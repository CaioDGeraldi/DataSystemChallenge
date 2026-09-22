from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from apps.empresas.models import Empresa, Gestor

from .models import Cliente


class ClienteTests(TestCase):
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
        self.assertEqual(self.usuario.cliente, cliente)
        self.assertEqual(cliente.usuario, self.usuario)
        self.assertIsNotNone(cliente.cadastrado_em)

    def test_mesmo_usuario_pode_ser_cliente_e_gestor(self):
        cliente = Cliente.objects.create(usuario=self.usuario, empresa=self.empresa)
        gestor = Gestor.objects.create(usuario=self.usuario, empresa=self.empresa)
        self.assertEqual(cliente.usuario_id, gestor.usuario_id)
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(cliente.usuario.get_full_name(), "Ana Silva")
        self.assertEqual(gestor.usuario.cpf, "52998224725")

    def test_usuario_nao_pode_ter_segundo_cliente_em_outra_empresa(self):
        outra_empresa = Empresa.objects.create(nome="Empresa B", cnpj="11444777000161")
        Cliente.objects.create(usuario=self.usuario, empresa=self.empresa)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Cliente.objects.create(usuario=self.usuario, empresa=outra_empresa)

    def test_cliente_protege_usuario_e_empresa_contra_exclusao(self):
        Cliente.objects.create(usuario=self.usuario, empresa=self.empresa)
        for entidade in (self.usuario, self.empresa):
            with self.subTest(entidade=type(entidade).__name__), self.assertRaises(ProtectedError):
                entidade.delete()
