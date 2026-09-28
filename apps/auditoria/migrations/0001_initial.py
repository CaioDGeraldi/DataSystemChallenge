import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name="EventoAuditoria",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("tipo_evento", models.CharField(max_length=100)),
                ("operacao", models.CharField(choices=[("INSERT", "INSERT"), ("UPDATE", "UPDATE"), ("DELETE", "DELETE")], max_length=6)),
                ("tabela_origem", models.CharField(max_length=63)),
                ("registro_id", models.CharField(max_length=255)),
                ("empresa_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("loja_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("usuario_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("credencial_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("origem", models.CharField(blank=True, choices=[("GESTAO_WEB", "Gestão Web"), ("API", "API"), ("SISTEMA", "Sistema")], max_length=10, null=True)),
                ("ocorrido_em", models.DateTimeField(default=django.utils.timezone.now)),
                ("dados_anteriores", models.JSONField(blank=True, null=True)),
                ("dados_novos", models.JSONField(blank=True, null=True)),
            ],
            options={
                "indexes": [
                    models.Index(fields=["ocorrido_em"], name="auditoria_ocorrido_idx"),
                    models.Index(fields=["empresa_id", "ocorrido_em"], name="auditoria_empresa_ocorrido_idx"),
                    models.Index(fields=["tabela_origem", "registro_id"], name="auditoria_tabela_registro_idx"),
                ],
            },
        ),
        migrations.RunSQL(
            sql="""
                CREATE FUNCTION auditoria_evento_append_only()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    RAISE EXCEPTION 'EventoAuditoria é append-only: % não permitido', TG_OP
                        USING ERRCODE = '55000';
                END;
                $$;

                CREATE TRIGGER auditoria_evento_append_only_trg
                BEFORE UPDATE OR DELETE ON auditoria_eventoauditoria
                FOR EACH ROW EXECUTE FUNCTION auditoria_evento_append_only();
            """,
            reverse_sql="""
                DROP TRIGGER auditoria_evento_append_only_trg ON auditoria_eventoauditoria;
                DROP FUNCTION auditoria_evento_append_only();
            """,
        ),
    ]
