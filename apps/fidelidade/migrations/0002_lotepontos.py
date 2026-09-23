from decimal import Decimal

import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("fidelidade", "0001_initial"),
        ("empresas", "0009_politica_arredondamento_pontos"),
    ]

    operations = [
        migrations.CreateModel(
            name="LotePontos",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("compra", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="lote_pontos", to="fidelidade.compra")),
                ("cliente", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="lotes_pontos", to="clientes.cliente")),
                ("pontos_base", models.DecimalField(max_digits=24, decimal_places=4, validators=[django.core.validators.MinValueValidator(Decimal("0"))])),
                ("pontos_concedidos", models.DecimalField(max_digits=24, decimal_places=4, validators=[django.core.validators.MinValueValidator(Decimal("0"))])),
                ("pontos_por_real_aplicado", models.DecimalField(max_digits=12, decimal_places=2, validators=[django.core.validators.MinValueValidator(Decimal("0"))])),
                ("precisao_pontos_aplicada", models.PositiveIntegerField(choices=[(0, "0"), (1, "1"), (2, "2"), (4, "4")])),
                ("modo_arredondamento_aplicado", models.CharField(max_length=7, choices=[("HALF_UP", "HALF_UP"), ("DOWN", "DOWN"), ("UP", "UP")])),
                ("validade_pontos_meses_aplicada", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
                ("adquiridos_em", models.DateTimeField()),
                ("expira_em", models.DateTimeField()),
                ("criado_em", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
            ],
            options={"constraints": [
                models.CheckConstraint(condition=models.Q(pontos_base__gte=0), name="lote_base_nao_negativa"),
                models.CheckConstraint(condition=models.Q(pontos_concedidos__gte=0), name="lote_concessao_nao_negativa"),
                models.CheckConstraint(condition=models.Q(pontos_por_real_aplicado__gte=0), name="lote_taxa_nao_negativa"),
                models.CheckConstraint(condition=models.Q(precisao_pontos_aplicada__in=[0, 1, 2, 4]), name="lote_precisao_valida"),
                models.CheckConstraint(condition=models.Q(modo_arredondamento_aplicado__in=["HALF_UP", "DOWN", "UP"]), name="lote_arredondamento_valido"),
                models.CheckConstraint(condition=models.Q(validade_pontos_meses_aplicada__gt=0), name="lote_validade_positiva"),
            ]},
        ),
    ]
