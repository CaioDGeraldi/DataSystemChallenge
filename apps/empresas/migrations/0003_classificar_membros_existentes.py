from django.db import migrations, models


def classificar_gestores(apps, schema_editor):
    MembroEmpresa = apps.get_model("empresas", "MembroEmpresa")
    MembroEmpresa.objects.using(schema_editor.connection.alias).all().update(papel="GESTOR", ativo=True)


class Migration(migrations.Migration):
    dependencies = [("empresas", "0002_renomear_gestor")]

    operations = [
        migrations.AddField(
            model_name="membroempresa", name="ativo", field=models.BooleanField(default=True)
        ),
        migrations.AddField(
            model_name="membroempresa", name="papel",
            field=models.CharField(max_length=13, null=True, choices=[("ADMINISTRADOR", "Administrador"), ("GESTOR", "Gestor")]),
        ),
        migrations.RunPython(classificar_gestores, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="membroempresa", name="papel",
            field=models.CharField(max_length=13, choices=[("ADMINISTRADOR", "Administrador"), ("GESTOR", "Gestor")]),
        ),
    ]
