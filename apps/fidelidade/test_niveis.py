from datetime import timedelta
from decimal import Decimal, Inexact, localcontext
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from apps.clientes.models import Cliente

from .eventos import cancelar_evento, criar_evento
from .escrita_niveis import _permitir_escrita_nivel
from .models import LotePontos, NivelFidelidade
from .niveis import classificar_cliente, criar_nivel, editar_nivel, excluir_nivel, listar_niveis
from .test_resgates import DadosResgates


class DadosNiveis(DadosResgates):
    def nivel(self, nome='Inicial', pontos='0.0000', request=None):
        return criar_nivel(
            request or self.request(),
            nome=nome,
            pontos_minimos=Decimal(pontos),
        )

    def faixas(self):
        return (
            self.nivel('Inicial'),
            self.nivel('Intermediário', '1000'),
            self.nivel('Avançado', '5000'),
        )


class NivelDominioTests(DadosNiveis, TestCase):
    def test_model_nome_normalizado_limite_e_decimal_24_4(self):
        inicial = self.nivel('  Nome livre \t')
        self.assertEqual(inicial.nome, 'Nome livre')
        self.assertEqual(str(inicial), 'Nome livre')
        maior = self.nivel(' ' + 'A' * 255 + ' ', '99999999999999999999.9999')
        maior.refresh_from_db()
        self.assertEqual(len(maior.nome), 255)
        self.assertEqual(
            str(maior.pontos_minimos),
            '99999999999999999999.9999',
        )
        campo = NivelFidelidade._meta.get_field('pontos_minimos')
        self.assertEqual((campo.max_digits, campo.decimal_places), (24, 4))
        self.assertEqual(
            {f.name for f in NivelFidelidade._meta.fields},
            {
                'id',
                'empresa',
                'nome',
                'pontos_minimos',
                'bonus_pontos_percentual',
                'desconto_percentual',
            },
        )

    def test_nome_invalido_e_valores_nao_representaveis(self):
        self.nivel()
        for nome in ('', ' \t', 'a' * 256, None, 123):
            with self.subTest(nome=nome), self.assertRaises(ValidationError):
                criar_nivel(
                    self.request(),
                    nome=nome,
                    pontos_minimos=Decimal('1'),
                )
        for pontos in (
            Decimal('-1'),
            Decimal('.00001'),
            Decimal('100000000000000000000'),
            Decimal('NaN'),
            Decimal('sNaN'),
            Decimal('Infinity'),
            1.0,
            True,
            '1',
            None,
        ):
            with self.subTest(pontos=pontos), self.assertRaises(ValidationError):
                criar_nivel(
                    self.request(),
                    nome='Inválido',
                    pontos_minimos=pontos,
                )
        self.assertEqual(NivelFidelidade.objects.count(), 1)

    def test_primeiro_zero_duplicidade_e_mesmo_threshold_em_outro_tenant(self):
        with self.assertRaises(ValidationError):
            self.nivel('Sem início', '1')
        self.assertFalse(NivelFidelidade.objects.exists())
        self.nivel()
        with self.assertRaises(ValidationError):
            self.nivel('Duplicado')
        externo = self.nivel(request=self.request(self.outro_membro))
        self.assertEqual(externo.empresa_id, self.outra.pk)
        self.assertEqual(NivelFidelidade.objects.count(), 2)

    def test_ordenacao_usa_threshold_sem_ordem_e_nomes_nao_sao_enums(self):
        inicial = self.nivel('VIP')
        alto = self.nivel('Standard', '5000')
        medio = self.nivel('VIP', '1000')  # Unicidade é do threshold, não do nome.
        self.assertEqual(
            list(listar_niveis(self.request())),
            [inicial, medio, alto],
        )
        self.assertEqual(
            list(NivelFidelidade.objects.all()),
            [inicial, medio, alto],
        )

    def test_nao_mover_zero_nem_excluir_zero_com_outros_niveis(self):
        zero, meio, _ = self.faixas()
        antes = list(NivelFidelidade.objects.values())
        with self.assertRaises(ValidationError):
            editar_nivel(
                self.request(),
                zero.pk,
                nome='Movido',
                pontos_minimos=Decimal('1'),
            )
        with self.assertRaises(ValidationError):
            excluir_nivel(self.request(), zero.pk)
        self.assertEqual(list(NivelFidelidade.objects.values()), antes)
        with self.assertRaises(ValidationError):
            editar_nivel(
                self.request(),
                meio.pk,
                nome='Colisão',
                pontos_minimos=Decimal('5000'),
            )
        self.assertEqual(list(NivelFidelidade.objects.values()), antes)

    def test_edicao_valida_exclusao_intermediaria_e_ultimo_nivel(self):
        zero, meio, alto = self.faixas()
        editado = editar_nivel(
            self.request(),
            meio.pk,
            nome='  Novo nome  ',
            pontos_minimos=Decimal('2500.1250'),
        )
        self.assertEqual(
            (editado.nome, editado.pontos_minimos),
            ('Novo nome', Decimal('2500.1250')),
        )
        excluir_nivel(self.request(), meio.pk)
        excluir_nivel(self.request(), alto.pk)
        with self.assertRaises(ValidationError):
            editar_nivel(
                self.request(),
                zero.pk,
                nome='Sem zero',
                pontos_minimos=Decimal('1'),
            )
        excluir_nivel(self.request(), zero.pk)
        self.assertFalse(NivelFidelidade.objects.exists())
        self.assertIsNone(classificar_cliente(self.cliente).nivel)

    def test_tenant_imutavel_ate_com_update_fields_e_relacao_protect(self):
        zero = self.nivel()
        zero.empresa = self.outra
        with self.assertRaises(ValidationError) as erro:
            zero.full_clean()
        self.assertIn('empresa', erro.exception.message_dict)
        # Exercita a validação de tenant, sem parar antes na guarda de escrita.
        with self.assertRaises(ValidationError) as erro:
            with _permitir_escrita_nivel(zero):
                zero.save(update_fields=['nome'])
        self.assertIn('empresa', erro.exception.message_dict)
        with self.assertRaises(ProtectedError) as erro, transaction.atomic():
            self.empresa.delete()
        self.assertIn(zero, erro.exception.protected_objects)
        self.assertEqual(
            NivelFidelidade.objects.get().empresa_id,
            self.empresa.pk,
        )
        with self.assertRaises(ValidationError):
            NivelFidelidade(
                empresa_id=999999,
                nome='Inexistente',
                pontos_minimos=Decimal('0'),
            ).full_clean()

    def test_escritas_normais_exigem_service_e_nao_perdem_invariante(self):
        zero = self.nivel()
        valores = dict(empresa=self.empresa, nome='Avulso', pontos_minimos=Decimal('1'))
        for operacao in (
            lambda: NivelFidelidade(**valores).save(),
            lambda: NivelFidelidade.objects.create(**valores),
            lambda: NivelFidelidade.objects.bulk_create([NivelFidelidade(**valores)]),
            lambda: NivelFidelidade.objects.update(pontos_minimos=Decimal('1')),
            lambda: NivelFidelidade.objects.bulk_update([zero], ['nome']),
            zero.save,
            zero.delete,
            lambda: NivelFidelidade.objects.all().delete(),
        ):
            with self.assertRaises(ValidationError):
                operacao()
        self.assertEqual(
            NivelFidelidade.objects.get().pontos_minimos,
            Decimal('0'),
        )

    def test_constraints_postgresql_defesa_final_com_savepoints(self):
        zero = self.nivel()
        # Bypass interno deliberado apenas para exercitar as constraints SQL.
        with self.assertRaises(IntegrityError) as erro, transaction.atomic():
            NivelFidelidade._base_manager.filter(pk=zero.pk).update(
                pontos_minimos=Decimal('-1'),
            )
        self.assertEqual(
            erro.exception.__cause__.diag.constraint_name,
            'nivel_threshold_nao_negativo',
        )
        with self.assertRaises(IntegrityError) as erro, transaction.atomic():
            NivelFidelidade._base_manager.bulk_create(
                [
                    NivelFidelidade(
                        empresa=self.empresa,
                        nome='Duplicado',
                        pontos_minimos=Decimal('0'),
                    ),
                ],
            )
        self.assertEqual(
            erro.exception.__cause__.diag.constraint_name,
            'nivel_empresa_threshold_unico',
        )
        self.assertEqual(NivelFidelidade.objects.count(), 1)

    def test_service_autorizacao_contexto_ativo_gestor_inativo_e_tenant(self):
        zero = self.nivel()
        externo = self.nivel(request=self.request(self.outro_membro))
        for id_externo in (externo.pk, 999999):
            with self.assertRaises(PermissionDenied):
                editar_nivel(
                    self.request(),
                    id_externo,
                    nome='Invasão',
                    pontos_minimos=Decimal('0'),
                )
            with self.assertRaises(PermissionDenied):
                excluir_nivel(self.request(), id_externo)
        for papel, ativo in (('GESTOR', True), ('ADMINISTRADOR', False)):
            self.membro.papel, self.membro.ativo = papel, ativo
            self.membro.save()
            for operacao in (
                lambda: listar_niveis(self.request()),
                lambda: self.nivel(),
                lambda: editar_nivel(self.request(), zero.pk, nome='Negado', pontos_minimos=Decimal('0')),
                lambda: excluir_nivel(self.request(), zero.pk),
            ):
                with self.assertRaises(PermissionDenied):
                    operacao()
        self.assertEqual(NivelFidelidade.objects.count(), 2)

    def test_rollback_se_persistencia_falhar_depois_do_insert(self):
        salvar = NivelFidelidade.save

        def falhar(nivel, *args, **kwargs):
            salvar(nivel, *args, **kwargs)
            raise ValidationError('Falha posterior')

        with patch.object(NivelFidelidade, 'save', falhar), self.assertRaises(ValidationError):
            self.nivel()
        self.assertFalse(NivelFidelidade.objects.exists())
        self.nivel()  # Transação externa permanece utilizável.


class ClassificacaoNivelTests(DadosNiveis, TestCase):
    def test_sem_niveis_sem_lotes_e_com_lotes(self):
        resultado = classificar_cliente(self.cliente)
        self.assertIsNone(resultado.nivel)
        self.assertIsInstance(resultado.pontos_para_nivel, Decimal)
        self.assertEqual(resultado.pontos_para_nivel, Decimal('0.0000'))
        self.lote('123.45')
        resultado = classificar_cliente(self.cliente)
        self.assertIsNone(resultado.nivel)
        self.assertEqual(resultado.pontos_para_nivel, Decimal('123.4500'))

    def test_limites_exatos_entre_faixas_e_ultimo_sem_teto(self):
        zero, meio, alto = self.faixas()
        self.assertEqual(classificar_cliente(self.cliente).nivel, zero)
        for concessao, total, nivel in (
            ('999.99', '999.99', zero),
            ('.01', '1000', meio),
            ('3999.99', '4999.99', meio),
            ('.01', '5000', alto),
            ('9000', '14000', alto),
        ):
            self.lote(concessao)
            resultado = classificar_cliente(self.cliente)
            self.assertEqual(
                (resultado.nivel, resultado.pontos_para_nivel),
                (nivel, Decimal(total)),
            )

    def test_threshold_e_pontos_fracionarios_exatos(self):
        zero = self.nivel()
        fracionario = self.nivel('Fração', '.0002')
        self.configurar(pontos_por_real=Decimal('.01'))
        self.lote('.01')
        self.assertEqual(classificar_cliente(self.cliente).nivel, zero)
        self.lote('.01')
        resultado = classificar_cliente(self.cliente)
        self.assertEqual(
            (resultado.nivel, resultado.pontos_para_nivel),
            (fracionario, Decimal('.0002')),
        )

    def test_soma_pode_exceder_um_lote_sem_truncar_e_independe_do_contexto_decimal(
        self,
    ):
        self.nivel()
        alto = self.nivel('Sem teto', '99999999999999999999.9999')
        self.configurar(pontos_por_real=Decimal('9999999999.99'))
        self.lote('9999999999.99')
        self.lote('9999999999.99')
        with localcontext() as contexto:
            contexto.prec = 3
            contexto.traps[Inexact] = True
            resultado = classificar_cliente(self.cliente)
        self.assertEqual(resultado.nivel, alto)
        self.assertEqual(
            resultado.pontos_para_nivel,
            Decimal('199999999999600000000.0002'),
        )

    def test_expiracao_resgate_e_inatividade_nao_reduzem_nivel(self):
        _, _, alto = self.faixas()
        self.lote('200', ocorrida_em=self.instante.replace(year=2020))
        self.lote('5000')
        antes = list(LotePontos.objects.values())
        resultado = classificar_cliente(self.cliente)
        self.resgatar(pontos=5000)
        self.configurar(periodo_cliente_ativo_dias=1)
        with patch(
            'apps.fidelidade.models.timezone.now',
            return_value=self.instante + timedelta(days=10000),
        ):
            depois = classificar_cliente(self.cliente)
        self.assertEqual(resultado, depois)
        self.assertEqual(
            (depois.nivel, depois.pontos_para_nivel),
            (alto, Decimal('5200')),
        )
        self.assertEqual(list(LotePontos.objects.values()), antes)

    def test_campanha_conta_concedidos_e_mudanca_de_threshold_reclassifica(
        self,
    ):
        zero = self.nivel()
        alto = self.nivel('Campanha', '1500')
        evento = criar_evento(
            self.request(),
            nome='2x',
            escopo='EMPRESA',
            inicio_em=self.instante - timedelta(days=1),
            fim_em=self.instante + timedelta(days=1),
            efeitos=[{'tipo': 'MULTIPLICADOR_PONTOS', 'valor': Decimal('2.0000')}],
        )
        self.lote('1000')
        antes = list(LotePontos.objects.values())
        cancelar_evento(self.request(), evento.pk)
        self.configurar(pontos_por_real=Decimal('9'))
        with patch(
            'apps.fidelidade.services.resolver_efeito_evento',
            side_effect=AssertionError('Sem recálculo'),
        ):
            resultado = classificar_cliente(self.cliente)
        self.assertEqual(
            (resultado.nivel, resultado.pontos_para_nivel),
            (alto, Decimal('2000')),
        )
        editar_nivel(
            self.request(),
            alto.pk,
            nome='Mais exigente',
            pontos_minimos=Decimal('2500'),
        )
        self.assertEqual(classificar_cliente(self.cliente).nivel, zero)
        self.assertEqual(list(LotePontos.objects.values()), antes)

    def test_cliente_persistido_tenant_e_usuario_nao_adulteraveis(self):
        self.faixas()
        externo = self.nivel('Externo', request=self.request(self.outro_membro))
        self.lote('9000')
        self.assertEqual(
            classificar_cliente(self.cliente_externo).nivel,
            externo,
        )
        self.assertEqual(
            classificar_cliente(self.cliente_externo).pontos_para_nivel,
            Decimal('0'),
        )
        for cliente in (
            None,
            Cliente(),
            Cliente(pk=999999, empresa=self.empresa, usuario=self.usuario),
            Cliente(
                pk=self.cliente.pk,
                empresa=self.outra,
                usuario=self.usuario,
            ),
            Cliente(
                pk=self.cliente.pk,
                empresa=self.empresa,
                usuario=self.outro_usuario,
            ),
        ):
            with self.assertRaises(ValidationError):
                classificar_cliente(cliente)
        self.assertNotIn('nivel', {f.name for f in Cliente._meta.fields})
        self.assertNotIn(
            'pontos_acumulados',
            {f.name for f in Cliente._meta.fields},
        )
