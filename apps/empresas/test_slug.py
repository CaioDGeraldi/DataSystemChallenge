from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from .models import Empresa


class SlugTests(TestCase):
    def test_slug_unico_e_obrigatorio(self):
        Empresa.objects.create(nome="Empresa A", slug="empresa", cnpj="11222333000181")
        for slug in ("empresa", "", None):
            with self.subTest(slug=slug), self.assertRaises(ValidationError):
                Empresa.objects.create(nome="Empresa B", slug=slug, cnpj="11444777000161")

    def test_slug_imutavel_e_nome_pode_mudar(self):
        empresa = Empresa.objects.create(nome="Empresa A", slug="empresa-a", cnpj="11222333000181")
        empresa.nome = "Novo nome"
        empresa.save()
        self.assertEqual(empresa.slug, "empresa-a")
        for parcial in (False, True):
            with self.subTest(parcial=parcial):
                empresa.slug = "novo-slug"
                with self.assertRaises(ValidationError):
                    empresa.save(**({"update_fields": ["slug"]} if parcial else {}))
                empresa.refresh_from_db()
                self.assertEqual(empresa.slug, "empresa-a")


class MigracaoSlugTests(TransactionTestCase):
    def test_preserva_empresas_e_resolve_colisoes_deterministicamente(self):
        executor = MigrationExecutor(connection)
        destino = executor.loader.graph.leaf_nodes()
        origem = [("empresas", "0004_acessoloja_alter_membroempresa_empresa_and_more"),
                  ("clientes", "0002_alter_cliente_usuario_and_more")]
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(destino))
        executor.migrate(origem)
        EmpresaAntiga = executor.loader.project_state(origem).apps.get_model("empresas", "Empresa")
        nomes = ["Loja Á", "Loja A", "Loja A-2", "!!!", "x" * 255, "x" * 255]
        registros = [EmpresaAntiga.objects.create(nome=nome, cnpj=f"{i:014}") for i, nome in enumerate(nomes, 1)]
        executor = MigrationExecutor(connection)
        executor.migrate(destino)
        EmpresaNova = executor.loader.project_state(destino).apps.get_model("empresas", "Empresa")
        slugs = []
        for antigo in registros:
            novo = EmpresaNova.objects.get(pk=antigo.pk)
            self.assertEqual((novo.nome, novo.cnpj, novo.criado_em), (antigo.nome, antigo.cnpj, antigo.criado_em))
            self.assertTrue(novo.slug)
            self.assertLessEqual(len(novo.slug), 50)
            slugs.append(novo.slug)
        self.assertEqual(slugs[:4], ["loja-a", "loja-a-2", "loja-a-2-2", "empresa"])
        self.assertEqual(len(set(slugs)), len(registros))
