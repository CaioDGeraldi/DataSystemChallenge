from django.db import models
from django.utils import timezone


class EventoAuditoria(models.Model):
    """Evidência histórica; IDs são snapshots sem relações com o domínio."""

    class Operacao(models.TextChoices):
        INSERT = "INSERT", "INSERT"
        UPDATE = "UPDATE", "UPDATE"
        DELETE = "DELETE", "DELETE"

    class Origem(models.TextChoices):
        GESTAO_WEB = "GESTAO_WEB", "Gestão Web"
        API = "API", "API"
        SISTEMA = "SISTEMA", "Sistema"

    id = models.BigAutoField(primary_key=True)
    tipo_evento = models.CharField(max_length=100)
    operacao = models.CharField(max_length=6, choices=Operacao.choices)
    tabela_origem = models.CharField(max_length=63)
    registro_id = models.CharField(max_length=255)
    empresa_id = models.PositiveBigIntegerField(null=True, blank=True)
    loja_id = models.PositiveBigIntegerField(null=True, blank=True)
    usuario_id = models.PositiveBigIntegerField(null=True, blank=True)
    credencial_id = models.PositiveBigIntegerField(null=True, blank=True)
    origem = models.CharField(max_length=10, choices=Origem.choices, null=True, blank=True)
    ocorrido_em = models.DateTimeField(default=timezone.now)
    dados_anteriores = models.JSONField(null=True, blank=True)
    dados_novos = models.JSONField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["ocorrido_em"], name="auditoria_ocorrido_idx"),
            models.Index(fields=["empresa_id", "ocorrido_em"], name="auditoria_empresa_ocorrido_idx"),
            models.Index(fields=["tabela_origem", "registro_id"], name="auditoria_tabela_registro_idx"),
        ]
