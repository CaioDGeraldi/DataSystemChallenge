from django.db import migrations, models
from django.utils.text import slugify


def preencher_slugs(apps, schema_editor):
    Empresa = apps.get_model("empresas", "Empresa")
    empresas = Empresa.objects.using(schema_editor.connection.alias)
    usados = set()
    for empresa in empresas.order_by("pk").iterator():
        base = slugify(empresa.nome)[:50] or "empresa"
        candidato = base
        numero = 2
        while candidato in usados:
            sufixo = f"-{numero}"
            candidato = base[:50 - len(sufixo)] + sufixo
            numero += 1
        empresas.filter(pk=empresa.pk).update(slug=candidato)
        usados.add(candidato)


class Migration(migrations.Migration):
    dependencies = [("empresas", "0004_acessoloja_alter_membroempresa_empresa_and_more")]

    operations = [
        migrations.AddField(model_name="empresa", name="slug", field=models.SlugField(null=True, db_index=False)),
        migrations.RunPython(preencher_slugs, migrations.RunPython.noop),
        migrations.AlterField(model_name="empresa", name="slug", field=models.SlugField(unique=True)),
    ]
