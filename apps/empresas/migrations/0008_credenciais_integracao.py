import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("empresas", "0007_configuracao_fidelidade")]

    operations = [
        migrations.CreateModel(
            name="CredencialIntegracao",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nome", models.CharField(max_length=255)),
                ("identificador", models.CharField(editable=False, max_length=64, unique=True)),
                ("segredo_hash", models.CharField(editable=False, max_length=128)),
                ("escopo", models.CharField(choices=[("EMPRESA", "Empresa"), ("LOJAS", "Lojas")], max_length=7)),
                ("ativa", models.BooleanField(default=True)),
                ("criada_em", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("ultimo_uso_em", models.DateTimeField(blank=True, editable=False, null=True)),
                ("empresa", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="credenciais_integracao", to="empresas.empresa")),
                ("criada_por", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="credenciais_criadas", to="empresas.membroempresa")),
            ],
        ),
        migrations.CreateModel(
            name="CredencialAcessoLoja",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("credencial", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="acessos_lojas", to="empresas.credencialintegracao")),
                ("loja", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="acessos_credenciais", to="empresas.loja")),
            ],
            options={"constraints": [
                models.UniqueConstraint(fields=("credencial", "loja"), name="credencial_loja_unica"),
            ]},
        ),
    ]
