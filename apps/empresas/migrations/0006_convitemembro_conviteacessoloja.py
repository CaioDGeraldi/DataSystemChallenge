import apps.usuarios.validators
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("empresas", "0005_empresa_slug")]

    operations = [
        migrations.CreateModel(
            name="ConviteMembro",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("cpf", models.CharField(max_length=11, validators=[apps.usuarios.validators.validar_cpf], verbose_name="CPF")),
                ("papel", models.CharField(choices=[("ADMINISTRADOR", "Administrador"), ("GESTOR", "Gestor")], max_length=13)),
                ("token_hash", models.CharField(max_length=64, unique=True)),
                ("criado_em", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("expira_em", models.DateTimeField(editable=False)),
                ("aceito_em", models.DateTimeField(blank=True, null=True)),
                ("revogado_em", models.DateTimeField(blank=True, null=True)),
                ("empresa", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="convites", to="empresas.empresa")),
                ("criado_por", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="convites_criados", to="empresas.membroempresa")),
            ],
        ),
        migrations.CreateModel(
            name="ConviteAcessoLoja",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("convite", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="acessos_lojas", to="empresas.convitemembro")),
                ("loja", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="acessos_convites", to="empresas.loja")),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("convite", "loja"), name="convite_loja_unico")]},
        ),
    ]
