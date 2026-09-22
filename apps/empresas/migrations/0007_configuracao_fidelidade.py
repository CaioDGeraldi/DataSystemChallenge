from decimal import Decimal

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("empresas", "0006_convitemembro_conviteacessoloja")]

    operations = [
        migrations.CreateModel(
            name="ConfiguracaoFidelidadeEmpresa",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("empresa", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="configuracao_fidelidade", to="empresas.empresa")),
                ("pontos_por_real", models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("1.00"), validators=[django.core.validators.MinValueValidator(Decimal("0"))])),
                ("validade_pontos_meses", models.PositiveIntegerField(default=12, validators=[django.core.validators.MinValueValidator(1)])),
                ("resgate_minimo_pontos", models.PositiveIntegerField(default=100, validators=[django.core.validators.MinValueValidator(1)])),
                ("incremento_resgate_pontos", models.PositiveIntegerField(default=100, validators=[django.core.validators.MinValueValidator(1)])),
                ("valor_monetario_por_ponto", models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.05"), validators=[django.core.validators.MinValueValidator(Decimal("0.01"))])),
                ("periodo_cliente_ativo_dias", models.PositiveIntegerField(default=180, validators=[django.core.validators.MinValueValidator(1)])),
            ],
            options={"constraints": [
                models.CheckConstraint(condition=models.Q(pontos_por_real__gte=0), name="cfg_empresa_pontos_nao_negativos"),
                models.CheckConstraint(condition=models.Q(validade_pontos_meses__gt=0), name="cfg_empresa_validade_positiva"),
                models.CheckConstraint(condition=models.Q(resgate_minimo_pontos__gt=0), name="cfg_empresa_minimo_positivo"),
                models.CheckConstraint(condition=models.Q(incremento_resgate_pontos__gt=0), name="cfg_empresa_incremento_positivo"),
                models.CheckConstraint(condition=models.Q(valor_monetario_por_ponto__gt=0), name="cfg_empresa_valor_positivo"),
                models.CheckConstraint(condition=models.Q(periodo_cliente_ativo_dias__gt=0), name="cfg_empresa_periodo_positivo"),
            ]},
        ),
        migrations.CreateModel(
            name="OverrideFidelidadeLoja",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("loja", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="override_fidelidade", to="empresas.loja")),
                ("pontos_por_real", models.DecimalField(max_digits=12, decimal_places=2, validators=[django.core.validators.MinValueValidator(Decimal("0"))])),
            ],
            options={"constraints": [
                models.CheckConstraint(condition=models.Q(pontos_por_real__gte=0), name="override_loja_pontos_nao_negativos"),
            ]},
        ),
    ]
