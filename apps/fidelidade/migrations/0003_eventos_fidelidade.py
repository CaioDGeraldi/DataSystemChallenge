from decimal import Decimal

import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('fidelidade', '0002_lotepontos')]

    operations = [
        migrations.AddField(
            model_name='lotepontos', name='multiplicador_pontos_aplicado',
            field=models.DecimalField(max_digits=12, decimal_places=4, default=Decimal('1.0000'),
                                      validators=[django.core.validators.MinValueValidator(Decimal('0.0001'))]),
        ),
        migrations.AddConstraint(
            model_name='lotepontos',
            constraint=models.CheckConstraint(condition=models.Q(multiplicador_pontos_aplicado__gt=0), name='lote_multiplicador_positivo'),
        ),
        migrations.CreateModel(
            name='EventoFidelidade',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nome', models.CharField(max_length=255)),
                ('descricao', models.TextField(blank=True)),
                ('inicio_em', models.DateTimeField()),
                ('fim_em', models.DateTimeField()),
                ('escopo', models.CharField(max_length=7, choices=[('EMPRESA', 'Empresa'), ('LOJAS', 'Lojas')])),
                ('criado_em', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('cancelado_em', models.DateTimeField(null=True, blank=True, editable=False)),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='eventos_fidelidade', to='empresas.empresa')),
                ('criado_por', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='eventos_criados', to='empresas.membroempresa')),
            ],
            options={'constraints': [
                models.CheckConstraint(condition=models.Q(fim_em__gt=models.F('inicio_em')), name='evento_periodo_valido'),
                models.CheckConstraint(condition=models.Q(escopo__in=['EMPRESA', 'LOJAS']), name='evento_escopo_valido'),
            ]},
        ),
        migrations.CreateModel(
            name='EfeitoEvento',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('evento', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='efeitos', to='fidelidade.eventofidelidade')),
                ('tipo', models.CharField(max_length=20, choices=[('MULTIPLICADOR_PONTOS', 'Multiplicador de pontos')])),
                ('valor', models.DecimalField(max_digits=12, decimal_places=4, validators=[django.core.validators.MinValueValidator(Decimal('0.0001'))])),
            ],
            options={'constraints': [
                models.UniqueConstraint(fields=['evento', 'tipo'], name='evento_tipo_efeito_unico'),
                models.CheckConstraint(condition=models.Q(valor__gt=0), name='efeito_valor_positivo'),
                models.CheckConstraint(condition=models.Q(tipo='MULTIPLICADOR_PONTOS'), name='efeito_tipo_suportado'),
            ]},
        ),
        migrations.CreateModel(
            name='EventoLoja',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('evento', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='lojas_selecionadas', to='fidelidade.eventofidelidade')),
                ('loja', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='eventos_selecionados', to='empresas.loja')),
            ],
            options={'constraints': [models.UniqueConstraint(fields=['evento', 'loja'], name='evento_loja_unica')]},
        ),
        migrations.CreateModel(
            name='AplicacaoEfeitoEventoLote',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('lote', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='aplicacoes_eventos', to='fidelidade.lotepontos')),
                ('evento', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='aplicacoes_lotes', to='fidelidade.eventofidelidade')),
                ('efeito', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='aplicacoes_lotes', to='fidelidade.efeitoevento')),
                ('tipo_aplicado', models.CharField(max_length=20, choices=[('MULTIPLICADOR_PONTOS', 'Multiplicador de pontos')])),
                ('valor_aplicado', models.DecimalField(max_digits=12, decimal_places=4, validators=[django.core.validators.MinValueValidator(Decimal('0.0001'))])),
                ('criado_em', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
            ],
            options={'constraints': [
                models.UniqueConstraint(fields=['lote', 'tipo_aplicado'], name='lote_tipo_evento_unico'),
                models.CheckConstraint(condition=models.Q(valor_aplicado__gt=0), name='aplicacao_valor_positivo'),
                models.CheckConstraint(condition=models.Q(tipo_aplicado='MULTIPLICADOR_PONTOS'), name='aplicacao_tipo_suportado'),
            ]},
        ),
    ]
