from decimal import Decimal

import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("clientes", "0002_alter_cliente_usuario_and_more"),
        ("empresas", "0008_credenciais_integracao"),
    ]

    operations = [
        migrations.CreateModel(
            name="Compra",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("identificador_externo", models.CharField(max_length=255)),
                ("valor", models.DecimalField(max_digits=12, decimal_places=2, validators=[django.core.validators.MinValueValidator(Decimal("0.01"))])),
                ("ocorrida_em", models.DateTimeField()),
                ("criada_em", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("loja", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="compras", to="empresas.loja")),
                ("cliente", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="compras", to="clientes.cliente")),
                ("credencial_origem", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="compras", to="empresas.credencialintegracao")),
            ],
            options={"constraints": [
                models.UniqueConstraint(fields=("loja", "identificador_externo"), name="compra_loja_identificador_unico"),
                models.CheckConstraint(condition=models.Q(valor__gt=0), name="compra_valor_positivo"),
            ]},
        ),
    ]
