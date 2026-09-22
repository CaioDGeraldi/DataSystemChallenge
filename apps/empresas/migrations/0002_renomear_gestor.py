from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("empresas", "0001_initial")]

    operations = [migrations.RenameModel(old_name="Gestor", new_name="MembroEmpresa")]
