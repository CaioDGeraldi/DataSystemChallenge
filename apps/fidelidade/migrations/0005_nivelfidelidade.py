from decimal import Decimal

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('fidelidade', '0004_resgate_alocacaoresgate')]

    operations = [
        migrations.CreateModel(
            name='NivelFidelidade',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nome', models.CharField(max_length=255)),
                ('pontos_minimos', models.DecimalField(max_digits=24, decimal_places=4,
                    validators=[django.core.validators.MinValueValidator(Decimal('0'))])),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                    related_name='niveis_fidelidade', to='empresas.empresa')),
            ],
            options={
                'ordering': ['pontos_minimos'],
                'constraints': [
                    models.UniqueConstraint(fields=['empresa', 'pontos_minimos'], name='nivel_empresa_threshold_unico'),
                    models.CheckConstraint(condition=models.Q(pontos_minimos__gte=0), name='nivel_threshold_nao_negativo'),
                ],
            },
        ),
    ]
