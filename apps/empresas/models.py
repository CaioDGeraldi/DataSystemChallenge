from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.hashers import identify_hasher
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.utils import timezone

from apps.usuarios.validators import normalizar_cpf, validar_cpf

from .validators import normalizar_cnpj, validar_cnpj
from .parametros import PADROES_FIDELIDADE, PRECISOES_PONTOS, MODOS_ARREDONDAMENTO_PONTOS


class Empresa(models.Model):
    nome = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    cnpj = models.CharField(
        "CNPJ",
        max_length=14,
        unique=True,
        validators=[validar_cnpj],
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    def clean(self):
        self.cnpj = normalizar_cnpj(self.cnpj)
        super().clean()
        if self.pk is not None:
            original = type(self)._base_manager.using(self._state.db).filter(pk=self.pk).values_list(
                "slug",
                flat=True,
            ).first()
            if original is not None and self.slug != original:
                raise ValidationError(
                    {"slug": "O slug não pode ser alterado após a criação."},
                )

    def save(self, *args, **kwargs):
        # Normalizar antes da validação de max_length e unicidade dos campos.
        self.cnpj = normalizar_cnpj(self.cnpj)
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.nome


class Loja(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="lojas")
    nome = models.CharField(max_length=255)
    cidade = models.CharField(max_length=255)

    def clean(self):
        super().clean()
        if self.pk is not None:
            empresa_original = (
                type(self)._base_manager.using(self._state.db)
                .filter(pk=self.pk).values_list(
                    "empresa_id",
                    flat=True,
                ).first()
            )
            if empresa_original is not None and self.empresa_id != empresa_original:
                raise ValidationError(
                    {
                        "empresa": "A Empresa não pode ser alterada após a criação.",
                    },
                )

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nome} ({self.cidade})"


class MembroEmpresa(models.Model):
    class Papel(models.TextChoices):
        ADMINISTRADOR = "ADMINISTRADOR", "Administrador"
        GESTOR = "GESTOR", "Gestor"

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="membros_empresas",
    )
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.PROTECT,
        related_name="membros",
    )
    papel = models.CharField(max_length=13, choices=Papel.choices)
    ativo = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["usuario", "empresa"],
                name="membro_usuario_empresa_unico",
            ),
        ]

    def clean(self):
        super().clean()
        if self.pk is not None:
            empresa_original = (
                type(self)._base_manager.using(self._state.db)
                .filter(pk=self.pk).values_list(
                    "empresa_id",
                    flat=True,
                ).first()
            )
            if empresa_original is not None and self.empresa_id != empresa_original:
                raise ValidationError(
                    {
                        "empresa": "A Empresa não pode ser alterada após a criação.",
                    },
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.usuario.get_full_name()} — {self.empresa}"


class AcessoLoja(models.Model):
    membro = models.ForeignKey(
        MembroEmpresa,
        on_delete=models.PROTECT,
        related_name="acessos_lojas",
    )
    loja = models.ForeignKey(
        Loja,
        on_delete=models.PROTECT,
        related_name="acessos_membros",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["membro", "loja"],
                name="acesso_membro_loja_unico",
            ),
        ]

    def clean(self):
        super().clean()
        if self.membro_id and self.loja_id:
            membro_empresa = MembroEmpresa.objects.filter(pk=self.membro_id).values_list(
                "empresa_id",
                flat=True,
            ).first()
            loja_empresa = Loja.objects.filter(pk=self.loja_id).values_list(
                "empresa_id",
                flat=True,
            ).first()
            if membro_empresa is not None and loja_empresa is not None and membro_empresa != loja_empresa:
                raise ValidationError(
                    {
                        "loja": "A Loja deve pertencer à mesma Empresa do membro.",
                    },
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.membro} — {self.loja}"


class ConviteMembro(models.Model):
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.PROTECT,
        related_name="convites",
    )
    cpf = models.CharField("CPF", max_length=11, validators=[validar_cpf])
    papel = models.CharField(max_length=13, choices=MembroEmpresa.Papel.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    criado_por = models.ForeignKey(
        MembroEmpresa,
        on_delete=models.PROTECT,
        related_name="convites_criados",
    )
    criado_em = models.DateTimeField(default=timezone.now, editable=False)
    expira_em = models.DateTimeField(editable=False)
    aceito_em = models.DateTimeField(null=True, blank=True)
    revogado_em = models.DateTimeField(null=True, blank=True)

    @property
    def estado(self):
        if self.aceito_em is not None:
            return "aceito"
        if self.revogado_em is not None:
            return "revogado"
        if timezone.now() >= self.expira_em:
            return "expirado"
        return "pendente"

    @property
    def pode_revogar(self):
        return self.estado == "pendente"

    def clean(self):
        super().clean()
        self.cpf = normalizar_cpf(self.cpf)
        if self.criado_por_id and self.empresa_id:
            empresa = MembroEmpresa.objects.filter(pk=self.criado_por_id).values_list(
                "empresa_id",
                flat=True,
            ).first()
            if empresa is not None and empresa != self.empresa_id:
                raise ValidationError(
                    {
                        "criado_por": "O criador deve pertencer à Empresa do convite.",
                    },
                )
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).values_list(
                "empresa_id",
                flat=True,
            ).first()
            if original is not None and original != self.empresa_id:
                raise ValidationError(
                    {
                        "empresa": "A Empresa não pode ser alterada após a criação.",
                    },
                )
            if self.papel != MembroEmpresa.Papel.GESTOR and self.acessos_lojas.exists():
                raise ValidationError(
                    {
                        "papel": "Somente convites de Gestor podem possuir Lojas.",
                    },
                )

    def save(self, *args, **kwargs):
        self.cpf = normalizar_cpf(self.cpf)
        if self._state.adding and self.expira_em is None:
            self.expira_em = self.criado_em + timedelta(days=7)
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"Convite {self.pk} — {self.empresa} ({self.get_papel_display()})"


class ConviteAcessoLoja(models.Model):
    convite = models.ForeignKey(
        ConviteMembro,
        on_delete=models.PROTECT,
        related_name="acessos_lojas",
    )
    loja = models.ForeignKey(
        Loja,
        on_delete=models.PROTECT,
        related_name="acessos_convites",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["convite", "loja"],
                name="convite_loja_unico",
            ),
        ]

    def clean(self):
        super().clean()
        convite = ConviteMembro.objects.filter(pk=self.convite_id).first()
        loja_empresa = Loja.objects.filter(pk=self.loja_id).values_list(
            "empresa_id",
            flat=True,
        ).first()
        if convite is not None:
            if convite.papel != MembroEmpresa.Papel.GESTOR:
                raise ValidationError(
                    {"convite": "Somente convites de Gestor recebem Lojas."},
                )
            if loja_empresa is not None and loja_empresa != convite.empresa_id:
                raise ValidationError(
                    {"loja": "A Loja deve pertencer à Empresa do convite."},
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


def _validar_tipos_parametros(instancia, exclude):
    erros = {}
    for campo in instancia._meta.fields:
        if campo.name in (exclude or ()):
            continue
        if not isinstance(campo, models.DecimalField) and type(campo) is not models.PositiveIntegerField:
            continue
        valor = getattr(instancia, campo.name)
        if isinstance(campo, models.DecimalField) and type(valor) is int:
            valor = Decimal(valor)
            setattr(instancia, campo.name, valor)
        if isinstance(campo, models.DecimalField) and not isinstance(valor, Decimal):
            erros[campo.name] = "Informe um Decimal, sem conversão de float."
        elif type(campo) is models.PositiveIntegerField and type(valor) is not int:
            erros[campo.name] = "Informe um número inteiro."
    if erros:
        raise ValidationError(erros)


class ConfiguracaoFidelidadeEmpresa(models.Model):
    precisao_pontos = models.PositiveIntegerField(
        choices=[(v, str(v)) for v in PRECISOES_PONTOS],
        default=PADROES_FIDELIDADE.precisao_pontos,
    )
    modo_arredondamento_pontos = models.CharField(
        max_length=7,
        choices=[(v, v) for v in MODOS_ARREDONDAMENTO_PONTOS],
        default=PADROES_FIDELIDADE.modo_arredondamento_pontos,
    )
    empresa = models.OneToOneField(
        Empresa,
        on_delete=models.PROTECT,
        related_name="configuracao_fidelidade",
    )
    pontos_por_real = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=PADROES_FIDELIDADE.pontos_por_real,
        validators=[MinValueValidator(Decimal("0"))],
    )
    validade_pontos_meses = models.PositiveIntegerField(
        default=PADROES_FIDELIDADE.validade_pontos_meses,
        validators=[MinValueValidator(1)],
    )
    resgate_minimo_pontos = models.PositiveIntegerField(
        default=PADROES_FIDELIDADE.resgate_minimo_pontos,
        validators=[MinValueValidator(1)],
    )
    incremento_resgate_pontos = models.PositiveIntegerField(
        default=PADROES_FIDELIDADE.incremento_resgate_pontos,
        validators=[MinValueValidator(1)],
    )
    valor_monetario_por_ponto = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=PADROES_FIDELIDADE.valor_monetario_por_ponto,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    periodo_cliente_ativo_dias = models.PositiveIntegerField(
        default=PADROES_FIDELIDADE.periodo_cliente_ativo_dias,
        validators=[MinValueValidator(1)],
    )

    inatividade_suspende_beneficios_nivel = models.BooleanField(default=False)
    promocao_retorno_ativa = models.BooleanField(default=False)
    beneficio_primeira_compra_apos_inatividade = models.CharField(
        max_length=40,
        choices=[
            ('SEM_BENEFICIOS_NIVEL', 'Sem benefícios de nível'),
            ('COM_BENEFICIOS_NIVEL', 'Com benefícios de nível'),
        ],
        default='SEM_BENEFICIOS_NIVEL',
    )
    modo_combinacao_descontos_percentuais = models.CharField(
        max_length=40,
        choices=[
            ('ADITIVO', 'Somar descontos'),
            ('SEQUENCIAL', 'Aplicar sobre o restante'),
        ],
        default='ADITIVO',
    )
    ordem_aplicacao_resgate = models.CharField(
        max_length=40,
        choices=[
            (
                'ANTES_DOS_DESCONTOS_PERCENTUAIS',
                'Resgate antes dos percentuais',
            ),
            (
                'DEPOIS_DOS_DESCONTOS_PERCENTUAIS',
                'Resgate depois dos percentuais',
            ),
        ],
        default='DEPOIS_DOS_DESCONTOS_PERCENTUAIS',
    )
    base_calculo_pontos = models.CharField(
        max_length=40,
        choices=[
            ('BRUTO', 'Valor original da compra'),
            ('LIQUIDO', 'Valor pago após descontos'),
        ],
        default='BRUTO',
    )
    modo_aplicacao_nivel = models.CharField(
        max_length=40,
        choices=[
            ('ANTES_DA_COMPRA', 'Nível anterior à compra'),
            ('ATINGIDO_NA_COMPRA', 'Nível atingido na compra'),
        ],
        default='ANTES_DA_COMPRA',
    )
    bonus_pontos_retorno_percentual = models.DecimalField(
        max_digits=7,
        decimal_places=4,
        default=Decimal("0.0000"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )
    desconto_retorno_percentual = models.DecimalField(
        max_digits=7,
        decimal_places=4,
        default=Decimal("0.0000"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    bonus_pontos_retorno_percentual__gte=0,
                    bonus_pontos_retorno_percentual__lte=100,
                ),
                name="cfg_bonus_retorno_percentual",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    desconto_retorno_percentual__gte=0,
                    desconto_retorno_percentual__lte=100,
                ),
                name="cfg_desconto_retorno_percentual",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    beneficio_primeira_compra_apos_inatividade__in=['SEM_BENEFICIOS_NIVEL', 'COM_BENEFICIOS_NIVEL'],
                ),
                name="cfg_beneficio_retorno_valido",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    modo_combinacao_descontos_percentuais__in=['ADITIVO', 'SEQUENCIAL'],
                ),
                name="cfg_combinacao_descontos_valida",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    ordem_aplicacao_resgate__in=[
                        'ANTES_DOS_DESCONTOS_PERCENTUAIS',
                        'DEPOIS_DOS_DESCONTOS_PERCENTUAIS',
                    ],
                ),
                name="cfg_ordem_resgate_valida",
            ),
            models.CheckConstraint(
                condition=models.Q(base_calculo_pontos__in=['BRUTO', 'LIQUIDO']),
                name="cfg_base_pontos_valida",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    modo_aplicacao_nivel__in=['ANTES_DA_COMPRA', 'ATINGIDO_NA_COMPRA'],
                ),
                name="cfg_modo_nivel_valido",
            ),
            models.CheckConstraint(
                condition=models.Q(pontos_por_real__gte=0),
                name="cfg_empresa_pontos_nao_negativos",
            ),
            models.CheckConstraint(
                condition=models.Q(precisao_pontos__in=[0, 1, 2, 4]),
                name="cfg_empresa_precisao_valida",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    modo_arredondamento_pontos__in=["HALF_UP", "DOWN", "UP"],
                ),
                name="cfg_empresa_arredondamento_valido",
            ),
            models.CheckConstraint(
                condition=models.Q(validade_pontos_meses__gt=0),
                name="cfg_empresa_validade_positiva",
            ),
            models.CheckConstraint(
                condition=models.Q(resgate_minimo_pontos__gt=0),
                name="cfg_empresa_minimo_positivo",
            ),
            models.CheckConstraint(
                condition=models.Q(incremento_resgate_pontos__gt=0),
                name="cfg_empresa_incremento_positivo",
            ),
            models.CheckConstraint(
                condition=models.Q(valor_monetario_por_ponto__gt=0),
                name="cfg_empresa_valor_positivo",
            ),
            models.CheckConstraint(
                condition=models.Q(periodo_cliente_ativo_dias__gt=0),
                name="cfg_empresa_periodo_positivo",
            ),
        ]

    def clean_fields(self, exclude=None):
        _validar_tipos_parametros(self, exclude)
        super().clean_fields(exclude=exclude)

    def clean(self):
        super().clean()
        if self.pk:
            original = type(self)._base_manager.using(self._state.db).filter(pk=self.pk).values_list(
                "empresa_id",
                flat=True,
            ).first()
            if original is not None and original != self.empresa_id:
                raise ValidationError(
                    {
                        "empresa": "A Empresa não pode ser alterada após a criação.",
                    },
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"Configuração de fidelidade — {self.empresa}"


class OverrideFidelidadeLoja(models.Model):
    loja = models.OneToOneField(
        Loja,
        on_delete=models.PROTECT,
        related_name="override_fidelidade",
    )
    pontos_por_real = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(pontos_por_real__gte=0),
                name="override_loja_pontos_nao_negativos",
            ),
        ]

    def clean_fields(self, exclude=None):
        _validar_tipos_parametros(self, exclude)
        super().clean_fields(exclude=exclude)

    def clean(self):
        super().clean()
        if self.pk:
            original = type(self)._base_manager.using(self._state.db).filter(pk=self.pk).values_list(
                "loja_id",
                flat=True,
            ).first()
            if original is not None and original != self.loja_id:
                raise ValidationError(
                    {"loja": "A Loja não pode ser alterada após a criação."},
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"Override de fidelidade — {self.loja}"


class CredencialIntegracao(models.Model):
    class Escopo(models.TextChoices):
        EMPRESA = "EMPRESA", "Empresa"
        LOJAS = "LOJAS", "Lojas"

    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.PROTECT,
        related_name="credenciais_integracao",
    )
    nome = models.CharField(max_length=255)
    identificador = models.CharField(max_length=64, unique=True, editable=False)
    segredo_hash = models.CharField(max_length=128, editable=False)
    escopo = models.CharField(max_length=7, choices=Escopo.choices)
    ativa = models.BooleanField(default=True)
    criada_por = models.ForeignKey(
        MembroEmpresa,
        on_delete=models.PROTECT,
        related_name="credenciais_criadas",
    )
    criada_em = models.DateTimeField(default=timezone.now, editable=False)
    ultimo_uso_em = models.DateTimeField(null=True, blank=True, editable=False)

    def clean(self):
        super().clean()
        try:
            identify_hasher(self.segredo_hash)
        except (ValueError, TypeError):
            raise ValidationError(
                {"segredo_hash": "Informe somente um hash de segredo válido."},
            ) from None
        if self.criada_por_id and self.empresa_id:
            empresa = MembroEmpresa.objects.filter(pk=self.criada_por_id).values_list(
                "empresa_id",
                flat=True,
            ).first()
            if empresa is not None and empresa != self.empresa_id:
                raise ValidationError(
                    {
                        "criada_por": "O criador deve pertencer à Empresa da credencial.",
                    },
                )
        if self.pk is not None:
            original = type(self)._base_manager.using(self._state.db).filter(pk=self.pk).values(
                "empresa_id",
                "escopo",
            ).first()
            if original is not None:
                erros = {}
                if original["empresa_id"] != self.empresa_id:
                    erros["empresa"] = "A Empresa não pode ser alterada após a criação."
                if original["escopo"] != self.escopo:
                    erros["escopo"] = "O escopo não pode ser alterado. Desative a credencial e crie outra."
                if erros:
                    raise ValidationError(erros)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.nome


_acessos_em_emissao = ContextVar("acessos_credencial_em_emissao", default=frozenset())


@contextmanager
def _permitir_acessos_iniciais(credencial, lojas):
    """Uso interno de criar_credencial, dentro da transação de emissão."""
    token = _acessos_em_emissao.set(
        frozenset((credencial.pk, loja.pk) for loja in lojas),
    )
    try:
        yield
    finally:
        _acessos_em_emissao.reset(token)


class CredencialAcessoLoja(models.Model):
    credencial = models.ForeignKey(
        CredencialIntegracao,
        on_delete=models.PROTECT,
        related_name="acessos_lojas",
    )
    loja = models.ForeignKey(
        Loja,
        on_delete=models.PROTECT,
        related_name="acessos_credenciais",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["credencial", "loja"],
                name="credencial_loja_unica",
            ),
        ]

    def clean(self):
        super().clean()
        credencial = CredencialIntegracao.objects.filter(pk=self.credencial_id).first()
        loja_empresa = Loja.objects.filter(pk=self.loja_id).values_list(
            "empresa_id",
            flat=True,
        ).first()
        if credencial is not None:
            if credencial.escopo != CredencialIntegracao.Escopo.LOJAS:
                raise ValidationError(
                    {
                        "credencial": "Somente credenciais LOJAS recebem acessos individuais.",
                    },
                )
            if loja_empresa is not None and loja_empresa != credencial.empresa_id:
                raise ValidationError(
                    {"loja": "A Loja deve pertencer à Empresa da credencial."},
                )

        original = type(self)._base_manager.using(self._state.db).filter(pk=self.pk).values_list(
            "credencial_id",
            "loja_id",
        ).first() if self.pk is not None else None
        acesso = (self.credencial_id, self.loja_id)
        if original is not None:
            if original != acesso:
                raise ValidationError(
                    "O escopo emitido é imutável. Desative a credencial e crie outra.",
                )
        elif acesso not in _acessos_em_emissao.get():
            raise ValidationError(
                "Lojas só podem ser vinculadas durante a criação da credencial.",
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


@receiver(pre_delete, sender=CredencialAcessoLoja)
def _impedir_remocao_acesso_credencial(sender, instance, **kwargs):
    # pre_delete também protege QuerySet.delete() e o manager reverso.
    raise ValidationError(
        "O escopo emitido é imutável. Desative a credencial e crie outra.",
    )
