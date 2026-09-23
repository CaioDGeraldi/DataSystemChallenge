from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("empresas", "0008_credenciais_integracao")]

    operations = [
        migrations.AddField(
            model_name="configuracaofidelidadeempresa", name="precisao_pontos",
            field=models.PositiveIntegerField(choices=[(0, "0"), (1, "1"), (2, "2"), (4, "4")], default=2),
        ),
        migrations.AddField(
            model_name="configuracaofidelidadeempresa", name="modo_arredondamento_pontos",
            field=models.CharField(choices=[("HALF_UP", "HALF_UP"), ("DOWN", "DOWN"), ("UP", "UP")], default="HALF_UP", max_length=7),
        ),
        migrations.AddConstraint(
            model_name="configuracaofidelidadeempresa",
            constraint=models.CheckConstraint(condition=models.Q(precisao_pontos__in=[0, 1, 2, 4]), name="cfg_empresa_precisao_valida"),
        ),
        migrations.AddConstraint(
            model_name="configuracaofidelidadeempresa",
            constraint=models.CheckConstraint(condition=models.Q(modo_arredondamento_pontos__in=["HALF_UP", "DOWN", "UP"]), name="cfg_empresa_arredondamento_valido"),
        ),
    ]
