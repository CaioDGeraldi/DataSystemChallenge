from datetime import datetime, timedelta, timezone as datetime_timezone
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import RequestFactory, TestCase

from apps.clientes.models import Cliente
from apps.empresas.models import Empresa, Loja, MembroEmpresa
from apps.empresas.services import criar_credencial, desativar_credencial
from apps.usuarios.services import CONTEXTO_SESSAO

from .exceptions import ClienteNaoEncontrado, IdempotenciaConflitante, LojaForaDoEscopo
from .models import Compra
from .services import registrar_compra


class DadosCompras:
    def setUp(self):
        super().setUp()
        self.usuario = get_user_model().objects.create_user("52998224725", first_name="Ana", last_name="Silva")
        self.outro_usuario = get_user_model().objects.create_user("11144477735")
        self.sem_vinculo = get_user_model().objects.create_user("12345678909")
        self.empresa = Empresa.objects.create(nome="Empresa A", slug="a", cnpj="11222333000181")
        self.outra = Empresa.objects.create(nome="Empresa B", slug="b", cnpj="11444777000161")
        self.loja = Loja.objects.create(empresa=self.empresa, nome="Centro", cidade="Araras")
        self.segunda = Loja.objects.create(empresa=self.empresa, nome="Shopping", cidade="Araras")
        self.externa = Loja.objects.create(empresa=self.outra, nome="Outra", cidade="Campinas")
        self.membro = MembroEmpresa.objects.create(usuario=self.usuario, empresa=self.empresa, papel="ADMINISTRADOR")
        self.outro_membro = MembroEmpresa.objects.create(usuario=self.usuario, empresa=self.outra, papel="ADMINISTRADOR")
        self.cliente = Cliente.objects.create(usuario=self.usuario, empresa=self.empresa)
        self.outro_cliente = Cliente.objects.create(usuario=self.outro_usuario, empresa=self.empresa)
        self.cliente_externo = Cliente.objects.create(usuario=self.sem_vinculo, empresa=self.outra)
        self.credencial, self.chave = self.emitir()
        self.instante = datetime(2026, 9, 23, 10, 30, tzinfo=datetime_timezone(timedelta(hours=-3)))

    def request(self, membro=None):
        membro = membro or self.membro
        request = RequestFactory().post("/")
        request.user = self.usuario
        request.session = {CONTEXTO_SESSAO: {
            "tipo_contexto": "gestao", "empresa_id": membro.empresa_id, "vinculo_id": membro.pk,
        }}
        return request

    def emitir(self, escopo="EMPRESA", lojas=(), membro=None):
        return criar_credencial(self.request(membro), nome="PDV", escopo=escopo, lojas=lojas)

    def dados(self, **alteracoes):
        return dict({
            "credencial": self.credencial, "loja_id": self.loja.pk,
            "cliente_cpf": self.usuario.cpf, "identificador_externo": "VENDA-000123",
            "valor": Decimal("199.90"), "ocorrida_em": self.instante,
        }, **alteracoes)

    def registrar(self, **alteracoes):
        return registrar_compra(**self.dados(**alteracoes))

    def model(self, **alteracoes):
        return Compra(**dict({
            "loja": self.loja, "cliente": self.cliente, "credencial_origem": self.credencial,
            "identificador_externo": "VENDA-000123", "valor": Decimal("199.90"),
            "ocorrida_em": self.instante,
        }, **alteracoes))


class CompraDominioTests(DadosCompras, TestCase):
    def test_compra_valida_persiste_fatos_sem_alterar_identidade(self):
        identidade = get_user_model().objects.values().get(pk=self.usuario.pk)
        compra, criada = self.registrar()
        compra.refresh_from_db()
        self.assertTrue(criada)
        self.assertEqual((compra.loja_id, compra.cliente_id, compra.credencial_origem_id),
                         (self.loja.pk, self.cliente.pk, self.credencial.pk))
        self.assertIsInstance(compra.valor, Decimal)
        self.assertEqual(compra.valor, Decimal("199.90"))
        self.assertEqual(compra.ocorrida_em, self.instante)
        self.assertIsNotNone(compra.criada_em)
        self.assertEqual(get_user_model().objects.values().get(pk=self.usuario.pk), identidade)
        self.assertEqual(Cliente.objects.count(), 3)

    def test_model_rejeita_cliente_cross_tenant(self):
        with self.assertRaises(ValidationError):
            self.model(cliente=self.cliente_externo).save()
        self.assertFalse(Compra.objects.exists())

    def test_model_rejeita_credencial_cross_tenant_e_loja_sem_escopo(self):
        externa, _ = self.emitir(membro=self.outro_membro)
        restrita, _ = self.emitir("LOJAS", [self.segunda])
        for credencial in (externa, restrita):
            with self.subTest(credencial=credencial.pk), self.assertRaises(ValidationError):
                self.model(credencial_origem=credencial).save()
        self.assertFalse(Compra.objects.exists())

    def test_service_revalida_escopo_empresa_lojas_e_objetos_adulterados(self):
        restrita, _ = self.emitir("LOJAS", [self.loja])
        restrita.escopo = "EMPRESA"
        for credencial, loja_id in ((self.credencial, self.externa.pk), (restrita, self.segunda.pk),
                                    (self.credencial, 999999)):
            with self.assertRaises(LojaForaDoEscopo):
                self.registrar(credencial=credencial, loja_id=loja_id)
        self.assertFalse(Compra.objects.exists())

    def test_cliente_inexistente_ou_somente_outro_tenant_nao_cria_vinculo(self):
        for cpf in (self.sem_vinculo.cpf, "39053344705"):
            with self.assertRaises(ClienteNaoEncontrado):
                self.registrar(cliente_cpf=cpf)
        self.assertEqual(Cliente.objects.count(), 3)
        self.assertEqual(get_user_model().objects.count(), 3)
        self.assertFalse(Compra.objects.exists())

    def test_valor_rejeita_float_zero_negativo_precisao_excesso_e_nao_finito(self):
        for valor in (1.1, 1, True, "1.00", Decimal("0"), Decimal("-1"), Decimal("0.001"),
                      Decimal("10000000000.00"), Decimal("NaN"), Decimal("Infinity")):
            with self.subTest(valor=valor), self.assertRaises(ValidationError):
                self.registrar(valor=valor)
        self.assertFalse(Compra.objects.exists())

    def test_valor_limites_inclusivos(self):
        for valor in (Decimal("0.01"), Decimal("9999999999.99")):
            compra, criada = self.registrar(identificador_externo=str(valor), valor=valor)
            compra.refresh_from_db()
            self.assertTrue(criada)
            self.assertEqual(compra.valor, valor)

    def test_constraint_valor_positivo_no_banco(self):
        compra, _ = self.registrar()
        for valor in (Decimal("0"), Decimal("-0.01")):
            with self.assertRaises(IntegrityError), transaction.atomic():
                Compra.objects.filter(pk=compra.pk).update(valor=valor)

    def test_identificador_strip_preserva_case_espacos_internos_e_limite(self):
        compra, _ = self.registrar(identificador_externo="  Venda  A-b \t")
        self.assertEqual(compra.identificador_externo, "Venda  A-b")
        diferente, criada = self.registrar(identificador_externo="venda  A-b")
        self.assertTrue(criada)
        self.assertNotEqual(compra.pk, diferente.pk)
        longa, _ = self.registrar(identificador_externo="  " + "A" * 255 + "  ")
        self.assertEqual(len(longa.identificador_externo), 255)

    def test_identificador_vazio_e_longo_rejeitados(self):
        for identificador in ("", " \n\t ", "a" * 256, None):
            with self.subTest(identificador=identificador), self.assertRaises(ValidationError):
                self.registrar(identificador_externo=identificador)
        self.assertFalse(Compra.objects.exists())

    def test_datetime_naive_invalido_rejeitado_sem_janela_temporal(self):
        for instante in (self.instante.replace(tzinfo=None), "2026-09-23", None):
            with self.assertRaises(ValidationError):
                self.registrar(ocorrida_em=instante)
        for ano in (2000, 2100):
            compra, _ = self.registrar(identificador_externo=str(ano), ocorrida_em=self.instante.replace(year=ano))
            self.assertEqual(compra.ocorrida_em.year, ano)

    def test_constraint_unica_mesma_loja_e_chave_em_loja_diferente(self):
        self.registrar()
        with self.assertRaises(IntegrityError), transaction.atomic():
            # Bypass deliberado para verificar a constraint SQL.
            Compra.objects.bulk_create([self.model()])
        segunda, criada = self.registrar(loja_id=self.segunda.pk)
        self.assertTrue(criada)
        self.assertEqual(segunda.loja_id, self.segunda.pk)
        self.assertEqual(Compra.objects.count(), 2)

    def test_relacoes_protect_e_historico_preservado_apos_desativacao(self):
        compra, _ = self.registrar()
        antes = Compra.objects.values().get(pk=compra.pk)
        for entidade in (self.loja, self.cliente, self.credencial):
            with self.subTest(entidade=type(entidade).__name__), self.assertRaises(ProtectedError):
                entidade.delete()
        desativar_credencial(self.request(), self.credencial.pk)
        compra.refresh_from_db()
        compra.full_clean()
        self.assertEqual(Compra.objects.values().get(pk=compra.pk), antes)
        with self.assertRaises(LojaForaDoEscopo):
            self.registrar(identificador_externo="OUTRA")


class CompraImutavelTests(DadosCompras, TestCase):
    def test_sete_fatos_imutaveis_em_clean_full_clean_save_e_save_parcial(self):
        compra, criada = self.registrar()
        self.assertTrue(criada)
        outra_credencial, _ = self.emitir()
        antes = Compra.objects.values().get(pk=compra.pk)
        alteracoes = {
            "loja": self.segunda,
            "cliente": self.outro_cliente,
            "credencial_origem": outra_credencial,
            "identificador_externo": "OUTRA-VENDA",
            "valor": Decimal("200.00"),
            "ocorrida_em": compra.ocorrida_em + timedelta(seconds=1),
            "criada_em": compra.criada_em + timedelta(seconds=1),
        }
        for campo, valor in alteracoes.items():
            for metodo in ("clean", "full_clean", "save", "parcial"):
                with self.subTest(campo=campo, metodo=metodo):
                    setattr(compra, campo, valor)
                    with self.assertRaises(ValidationError) as erro:
                        if metodo == "parcial":
                            compra.save(update_fields=[campo])
                        else:
                            getattr(compra, metodo)()
                    self.assertIn(campo, erro.exception.message_dict)
                    self.assertEqual(Compra.objects.values().get(pk=compra.pk), antes)
                    compra.refresh_from_db()

    def test_save_sem_alteracoes_e_historico_com_credencial_desativada(self):
        compra, _ = self.registrar()
        antes = Compra.objects.values().get(pk=compra.pk)
        compra.save()
        desativar_credencial(self.request(), self.credencial.pk)
        self.credencial.refresh_from_db()
        self.assertFalse(self.credencial.ativa)
        compra.refresh_from_db()
        compra.full_clean()
        compra.save()
        compra.save(update_fields=["valor", "credencial_origem"])
        self.assertEqual(Compra.objects.values().get(pk=compra.pk), antes)

    def test_instancia_reconstruida_com_pk_existente_nao_reescreve_origem(self):
        compra, _ = self.registrar()
        antes = Compra.objects.values().get(pk=compra.pk)
        outra_credencial, _ = self.emitir()
        reconstruida = Compra(**dict(antes, credencial_origem_id=outra_credencial.pk))
        with self.assertRaises(ValidationError) as erro:
            reconstruida.save()
        self.assertIn("credencial_origem", erro.exception.message_dict)
        self.assertEqual(Compra.objects.values().get(pk=compra.pk), antes)

    def test_update_fields_nao_dispensa_comparacao_dos_demais_fatos(self):
        compra, _ = self.registrar()
        antes = Compra.objects.values().get(pk=compra.pk)
        compra.identificador_externo = "OUTRA-VENDA"
        with self.assertRaises(ValidationError):
            compra.save(update_fields=["valor"])
        self.assertEqual(Compra.objects.values().get(pk=compra.pk), antes)

    def test_retry_retorna_original_sem_save_apos_congelamento(self):
        compra, _ = self.registrar()
        antes = Compra.objects.values().get(pk=compra.pk)
        with patch.object(Compra, "save", side_effect=AssertionError("Retry não deve salvar Compra")):
            retry, criada = self.registrar()
        self.assertFalse(criada)
        self.assertEqual(retry.pk, compra.pk)
        self.assertEqual(Compra.objects.count(), 1)
        self.assertEqual(Compra.objects.values().get(pk=compra.pk), antes)


class IdempotenciaCompraTests(DadosCompras, TestCase):
    def test_retry_equivalente_preserva_todos_campos_e_instante_equivalente(self):
        compra, criada = self.registrar()
        antes = Compra.objects.values().get(pk=compra.pk)
        retry, criada_retry = self.registrar(
            cliente_cpf="529.982.247-25", identificador_externo=" VENDA-000123 ",
            ocorrida_em=self.instante.astimezone(datetime_timezone.utc),
        )
        self.assertTrue(criada)
        self.assertFalse(criada_retry)
        self.assertEqual(retry.pk, compra.pk)
        self.assertEqual(Compra.objects.count(), 1)
        self.assertEqual(Compra.objects.values().get(pk=compra.pk), antes)

    def test_retry_com_outra_credencial_preserva_origem_inclusive_desativada(self):
        compra, _ = self.registrar()
        outra, _ = self.emitir("LOJAS", [self.loja])
        desativar_credencial(self.request(), self.credencial.pk)
        retry, criada = self.registrar(credencial=outra)
        self.assertFalse(criada)
        self.assertEqual(retry.pk, compra.pk)
        self.assertEqual(retry.credencial_origem_id, self.credencial.pk)
        self.assertEqual(retry.criada_em, compra.criada_em)

    def test_conflitos_cliente_valor_e_instante_preservam_original(self):
        compra, _ = self.registrar()
        antes = Compra.objects.values().get(pk=compra.pk)
        for alteracoes in ({"cliente_cpf": self.outro_usuario.cpf}, {"valor": Decimal("200.00")},
                           {"ocorrida_em": self.instante + timedelta(seconds=1)}):
            with self.subTest(alteracoes=alteracoes), self.assertRaises(IdempotenciaConflitante):
                self.registrar(**alteracoes)
            self.assertEqual(Compra.objects.count(), 1)
            self.assertEqual(Compra.objects.values().get(pk=compra.pk), antes)

    def test_erro_de_integridade_nao_relacionado_nao_e_convertido_em_retry(self):
        with patch("apps.fidelidade.services.Compra.save", side_effect=IntegrityError("Falha simulada")):
            with self.assertRaises(IntegrityError):
                self.registrar()
        self.assertFalse(Compra.objects.exists())
