from decimal import Decimal

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('fidelidade', '0003_eventos_fidelidade')]

    operations = [
        migrations.CreateModel(
            name='Resgate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('identificador_externo', models.CharField(max_length=255)),
                ('pontos_resgatados', models.DecimalField(max_digits=20, decimal_places=0, validators=[django.core.validators.MinValueValidator(Decimal('1'))])),
                ('resgate_minimo_pontos_aplicado', models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
                ('incremento_resgate_pontos_aplicado', models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
                ('valor_monetario_por_ponto_aplicado', models.DecimalField(max_digits=12, decimal_places=2, validators=[django.core.validators.MinValueValidator(Decimal('0.01'))])),
                ('valor_desconto', models.DecimalField(max_digits=32, decimal_places=2, validators=[django.core.validators.MinValueValidator(Decimal('0.01'))])),
                ('resgatado_em', models.DateTimeField(editable=False)),
                ('loja', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='resgates', to='empresas.loja')),
                ('cliente', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='resgates', to='clientes.cliente')),
                ('credencial_origem', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='resgates', to='empresas.credencialintegracao')),
            ],
            options={'constraints': [
                models.UniqueConstraint(fields=['loja', 'identificador_externo'], name='resgate_loja_identificador_unico'),
                models.CheckConstraint(condition=models.Q(pontos_resgatados__gt=0), name='resgate_pontos_positivos'),
                models.CheckConstraint(condition=models.Q(resgate_minimo_pontos_aplicado__gt=0), name='resgate_minimo_positivo'),
                models.CheckConstraint(condition=models.Q(incremento_resgate_pontos_aplicado__gt=0), name='resgate_incremento_positivo'),
                models.CheckConstraint(condition=models.Q(valor_monetario_por_ponto_aplicado__gt=0), name='resgate_taxa_positiva'),
                models.CheckConstraint(condition=models.Q(valor_desconto__gt=0), name='resgate_desconto_positivo'),
            ]},
        ),
        migrations.CreateModel(
            name='AlocacaoResgate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('pontos_consumidos', models.DecimalField(max_digits=24, decimal_places=4, validators=[django.core.validators.MinValueValidator(Decimal('0.0001'))])),
                ('resgate', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='alocacoes', to='fidelidade.resgate')),
                ('lote', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='alocacoes_resgate', to='fidelidade.lotepontos')),
            ],
            options={'constraints': [
                models.UniqueConstraint(fields=['resgate', 'lote'], name='alocacao_resgate_lote_unico'),
                models.CheckConstraint(condition=models.Q(pontos_consumidos__gt=0), name='alocacao_pontos_positivos'),
            ]},
        ),
    ]
