from datetime import datetime
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models, transaction
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.empresas.models import CredencialIntegracao, Loja
from apps.empresas.parametros import MODOS_ARREDONDAMENTO_PONTOS, PRECISOES_PONTOS

from .calculos import calcular_expiracao, calcular_pontos


class Compra(models.Model):
    loja = models.ForeignKey(Loja, on_delete=models.PROTECT, related_name="compras")
    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.PROTECT,
        related_name="compras",
    )
    credencial_origem = models.ForeignKey(
        CredencialIntegracao,
        on_delete=models.PROTECT,
        related_name="compras",
    )
    identificador_externo = models.CharField(max_length=255)
    valor = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    ocorrida_em = models.DateTimeField()
    criada_em = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["loja", "identificador_externo"],
                name="compra_loja_identificador_unico",
            ),
            models.CheckConstraint(
                condition=models.Q(valor__gt=0),
                name="compra_valor_positivo",
            ),
        ]

    def clean_fields(self, exclude=None):
        erros = {}
        if "identificador_externo" not in (exclude or ()):
            if isinstance(self.identificador_externo, str):
                self.identificador_externo = self.identificador_externo.strip()
            else:
                erros["identificador_externo"] = "Informe um identificador textual."
        if "valor" not in (exclude or ()) and not isinstance(self.valor, Decimal):
            erros["valor"] = "Informe um Decimal, sem conversão de float."
        if "ocorrida_em" not in (exclude or ()):
            if not isinstance(self.ocorrida_em, datetime) or timezone.is_naive(self.ocorrida_em):
                erros["ocorrida_em"] = "Informe uma data/hora com timezone."
        if erros:
            raise ValidationError(erros)
        super().clean_fields(exclude=exclude)

    def clean(self):
        super().clean()
        if self.pk is not None:
            campos = (
                "loja",
                "cliente",
                "credencial_origem",
                "identificador_externo",
                "valor",
                "ocorrida_em",
                "criada_em",
            )
            original = type(self)._base_manager.using(self._state.db).filter(pk=self.pk).values(
                *campos,
            ).first()
            if original is not None:
                erros = {
                    campo: "O fato histórico não pode ser alterado após a criação."
                    for campo in campos
                    if getattr(self, self._meta.get_field(campo).attname) != original[campo]
                }
                if erros:
                    raise ValidationError(erros)
                # Histórico inalterado não depende da autorização atual da credencial.
                return
        loja = Loja.objects.filter(pk=self.loja_id).first()
        cliente = Cliente.objects.filter(pk=self.cliente_id).first()
        credencial = CredencialIntegracao.objects.filter(pk=self.credencial_origem_id).first()
        if loja is not None and cliente is not None and loja.empresa_id != cliente.empresa_id:
            raise ValidationError(
                {"cliente": "Cliente e Loja devem pertencer à mesma Empresa."},
            )
        if loja is not None and credencial is not None:
            if loja.empresa_id != credencial.empresa_id:
                raise ValidationError(
                    {
                        "credencial_origem": "A credencial deve pertencer à Empresa da Loja.",
                    },
                )
            from apps.empresas.services import exigir_loja_autorizada

            try:
                exigir_loja_autorizada(credencial, loja)
            except PermissionDenied:
                raise ValidationError(
                    {
                        "credencial_origem": "Credencial não autorizada para a Loja.",
                    },
                ) from None

    def save(self, *args, **kwargs):
        # A unicidade concorrente é arbitrada pelo INSERT/constraint SQL, não por SELECT prévio.
        # O valor positivo também é validado pelos validators do campo.
        self.full_clean(validate_constraints=False)
        return super().save(*args, **kwargs)


class LotePontos(models.Model):
    beneficios_aplicados = models.JSONField(null=True, blank=True, editable=False)
    compra = models.OneToOneField(
        Compra,
        on_delete=models.PROTECT,
        related_name="lote_pontos",
    )
    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.PROTECT,
        related_name="lotes_pontos",
    )
    pontos_base = models.DecimalField(
        max_digits=24,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0"))],
    )
    pontos_concedidos = models.DecimalField(
        max_digits=24,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0"))],
    )
    pontos_por_real_aplicado = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    multiplicador_pontos_aplicado = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        default=Decimal("1.0000"),
        validators=[MinValueValidator(Decimal("0.0001"))],
    )
    precisao_pontos_aplicada = models.PositiveIntegerField(
        choices=[(v, str(v)) for v in PRECISOES_PONTOS],
    )
    modo_arredondamento_aplicado = models.CharField(
        max_length=7,
        choices=[(v, v) for v in MODOS_ARREDONDAMENTO_PONTOS],
    )
    validade_pontos_meses_aplicada = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    adquiridos_em = models.DateTimeField()
    expira_em = models.DateTimeField()
    criado_em = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(pontos_base__gte=0),
                name="lote_base_nao_negativa",
            ),
            models.CheckConstraint(
                condition=models.Q(pontos_concedidos__gte=0),
                name="lote_concessao_nao_negativa",
            ),
            models.CheckConstraint(
                condition=models.Q(pontos_por_real_aplicado__gte=0),
                name="lote_taxa_nao_negativa",
            ),
            models.CheckConstraint(
                condition=models.Q(multiplicador_pontos_aplicado__gt=0),
                name="lote_multiplicador_positivo",
            ),
            models.CheckConstraint(
                condition=models.Q(precisao_pontos_aplicada__in=[0, 1, 2, 4]),
                name="lote_precisao_valida",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    modo_arredondamento_aplicado__in=["HALF_UP", "DOWN", "UP"],
                ),
                name="lote_arredondamento_valido",
            ),
            models.CheckConstraint(
                condition=models.Q(validade_pontos_meses_aplicada__gt=0),
                name="lote_validade_positiva",
            ),
        ]

    def clean_fields(self, exclude=None):
        erros = {}
        for campo in (
            "pontos_base",
            "pontos_concedidos",
            "pontos_por_real_aplicado",
            "multiplicador_pontos_aplicado",
        ):
            if campo not in (exclude or ()) and not isinstance(getattr(self, campo), Decimal):
                erros[campo] = "Informe um Decimal, sem conversão de float."
        for campo in ("precisao_pontos_aplicada", "validade_pontos_meses_aplicada"):
            if campo not in (exclude or ()) and type(getattr(self, campo)) is not int:
                erros[campo] = "Informe um número inteiro."
        for campo in ("adquiridos_em", "expira_em", "criado_em"):
            valor = getattr(self, campo)
            if campo not in (exclude or ()) and (not isinstance(valor, datetime) or timezone.is_naive(valor)):
                erros[campo] = "Informe uma data/hora com timezone."
        if erros:
            raise ValidationError(erros)
        super().clean_fields(exclude=exclude)

    def clean(self):
        super().clean()
        # full_clean chama clean mesmo após erros de campos. Comparações e cálculos
        # precisam de tipos válidos (inclusive para Decimal não finito).
        self.clean_fields()
        campos = tuple(campo.name for campo in self._meta.fields if not campo.primary_key)
        if self.pk is not None:
            original = type(self)._base_manager.using(self._state.db).filter(pk=self.pk).values(
                *campos,
            ).first()
            if original is not None:
                erros = {
                    campo: "O fato histórico não pode ser alterado após a criação."
                    for campo in campos
                    if getattr(self, self._meta.get_field(campo).attname) != original[campo]
                }
                if erros:
                    raise ValidationError(erros)
                return
        # Validar dados persistidos, sem confiar em relações adulteradas em memória.
        compra = Compra.objects.select_related("cliente", "loja").filter(
            pk=self.compra_id,
        ).first()
        if compra is None:
            return  # A validação do FK informa a ausência da Compra.
        if self.cliente_id != compra.cliente_id or compra.cliente.empresa_id != compra.loja.empresa_id:
            raise ValidationError(
                {
                    "cliente": "O Cliente deve ser o mesmo da Compra e pertencer à Empresa da Loja.",
                },
            )
        if self.beneficios_aplicados is not None:
            from .beneficios import reavaliar_snapshot
            avaliacao = reavaliar_snapshot(
                self.beneficios_aplicados,
                compra.valor,
                compra.ocorrida_em,
                self.multiplicador_pontos_aplicado,
            )
            base, concedidos = avaliacao.pontos_base, avaliacao.pontos_concedidos
            politica = self.beneficios_aplicados['politica']
            for campo, snapshot in (
                ('pontos_por_real', 'pontos_por_real_aplicado'),
                ('precisao_pontos', 'precisao_pontos_aplicada'),
                ('modo_arredondamento_pontos', 'modo_arredondamento_aplicado'),
                ('validade_pontos_meses', 'validade_pontos_meses_aplicada'),
            ):
                if str(politica[campo]) != str(getattr(self, snapshot)):
                    raise ValidationError('Snapshots de política divergentes.')
        else:
            base, concedidos = calcular_pontos(
                compra.valor,
                self.pontos_por_real_aplicado,
                self.precisao_pontos_aplicada,
                self.modo_arredondamento_aplicado,
                self.multiplicador_pontos_aplicado,
            )
        esperados = {
            "pontos_base": base,
            "pontos_concedidos": concedidos,
            "adquiridos_em": compra.ocorrida_em,
            "expira_em": calcular_expiracao(
                compra.ocorrida_em,
                self.validade_pontos_meses_aplicada,
            ),
        }
        erros = {campo: "O valor deve corresponder à Compra e aos snapshots aplicados."
                 for campo, valor in esperados.items() if getattr(self, campo) != valor}
        if erros:
            raise ValidationError(erros)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


def _original_evento(instancia):
    if instancia.pk is None:
        return None
    return type(instancia)._base_manager.using(instancia._state.db).filter(
        pk=instancia.pk,
    ).values().first()


def _validar_historico_evento(instancia, original, exceto=()):
    erros = {
        campo.name: 'O fato histórico não pode ser alterado após a criação.'
        for campo in instancia._meta.fields
        if not campo.primary_key and campo.name not in exceto
        and getattr(instancia, campo.attname) != original[campo.attname]
    }
    if erros:
        raise ValidationError(erros)


def _validar_instantes_evento(instancia, campos, exclude=()):
    erros = {}
    for campo in campos:
        if campo in (exclude or ()):
            continue
        valor = getattr(instancia, campo)
        if campo == 'cancelado_em' and valor is None:
            continue
        if not isinstance(valor, datetime) or timezone.is_naive(valor):
            erros[campo] = 'Informe uma data/hora com timezone.'
    if erros:
        raise ValidationError(erros)


class _RegistroEvento(models.Model):
    """Escrita inicial exclusiva dos services; atualização valida todo o histórico."""
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        from .escrita_eventos import _exigir_escrita_eventos

        if _original_evento(self) is None:
            _exigir_escrita_eventos(self)
        self.full_clean()
        return super().save(*args, **kwargs)


class EventoFidelidade(_RegistroEvento):
    class Escopo(models.TextChoices):
        EMPRESA = 'EMPRESA', 'Empresa'
        LOJAS = 'LOJAS', 'Lojas'

    empresa = models.ForeignKey(
        'empresas.Empresa',
        on_delete=models.PROTECT,
        related_name='eventos_fidelidade',
    )
    nome = models.CharField(max_length=255)
    descricao = models.TextField(blank=True)
    inicio_em = models.DateTimeField()
    fim_em = models.DateTimeField()
    escopo = models.CharField(max_length=7, choices=Escopo.choices)
    criado_por = models.ForeignKey(
        'empresas.MembroEmpresa',
        on_delete=models.PROTECT,
        related_name='eventos_criados',
    )
    criado_em = models.DateTimeField(default=timezone.now, editable=False)
    cancelado_em = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(fim_em__gt=models.F('inicio_em')),
                name='evento_periodo_valido',
            ),
            models.CheckConstraint(
                condition=models.Q(escopo__in=['EMPRESA', 'LOJAS']),
                name='evento_escopo_valido',
            ),
        ]

    def save(self, *args, **kwargs):
        # Evita que um save inalterado de instância antiga apague cancelamento
        # concorrente entre a leitura da imutabilidade e o UPDATE.
        with transaction.atomic():
            if self.pk is not None:
                type(self)._base_manager.select_for_update().filter(pk=self.pk).first()
            return super().save(*args, **kwargs)

    @property
    def estado(self):
        if self.cancelado_em is not None:
            return 'CANCELADO'
        agora = timezone.now()
        if agora < self.inicio_em:
            return 'AGENDADO'
        if agora <= self.fim_em:
            return 'VIGENTE'
        return 'ENCERRADO'

    def clean_fields(self, exclude=None):
        _validar_instantes_evento(
            self,
            ('inicio_em', 'fim_em', 'criado_em', 'cancelado_em'),
            exclude,
        )
        super().clean_fields(exclude=exclude)

    def clean(self):
        super().clean()
        self.clean_fields()
        original = _original_evento(self)
        if original is not None:
            _validar_historico_evento(self, original, exceto=('cancelado_em',))
            if self.cancelado_em != original['cancelado_em']:
                if original['cancelado_em'] is not None or self.cancelado_em is None:
                    raise ValidationError(
                        {'cancelado_em': 'O cancelamento original é imutável.'},
                    )
                from .escrita_eventos import _exigir_escrita_eventos
                _exigir_escrita_eventos(self)
            return
        if self.cancelado_em is not None:
            raise ValidationError(
                {'cancelado_em': 'Um Evento deve ser criado sem cancelamento.'},
            )
        if self.fim_em <= self.inicio_em:
            raise ValidationError({'fim_em': 'O fim deve ser posterior ao início.'})
        from apps.empresas.models import MembroEmpresa
        if not MembroEmpresa.objects.filter(
            pk=self.criado_por_id,
            empresa_id=self.empresa_id,
            ativo=True,
            papel='ADMINISTRADOR',
        ).exists():
            raise ValidationError(
                {
                    'criado_por': 'O criador deve ser Administrador ativo da Empresa.',
                },
            )


class EfeitoEvento(_RegistroEvento):
    class Tipo(models.TextChoices):
        MULTIPLICADOR_PONTOS = 'MULTIPLICADOR_PONTOS', 'Multiplicador de pontos'

    evento = models.ForeignKey(
        EventoFidelidade,
        on_delete=models.PROTECT,
        related_name='efeitos',
    )
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    valor = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        validators=[MinValueValidator(Decimal('0.0001'))],
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['evento', 'tipo'],
                name='evento_tipo_efeito_unico',
            ),
            models.CheckConstraint(
                condition=models.Q(valor__gt=0),
                name='efeito_valor_positivo',
            ),
            models.CheckConstraint(
                condition=models.Q(tipo='MULTIPLICADOR_PONTOS'),
                name='efeito_tipo_suportado',
            ),
        ]

    def clean_fields(self, exclude=None):
        if 'valor' not in (exclude or ()) and not isinstance(self.valor, Decimal):
            raise ValidationError(
                {'valor': 'Informe um Decimal, sem conversão de float.'},
            )
        super().clean_fields(exclude=exclude)

    def clean(self):
        super().clean()
        self.clean_fields()
        original = _original_evento(self)
        if original is not None:
            _validar_historico_evento(self, original)


class EventoLoja(_RegistroEvento):
    evento = models.ForeignKey(
        EventoFidelidade,
        on_delete=models.PROTECT,
        related_name='lojas_selecionadas',
    )
    loja = models.ForeignKey(
        Loja,
        on_delete=models.PROTECT,
        related_name='eventos_selecionados',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['evento', 'loja'],
                name='evento_loja_unica',
            ),
        ]

    def clean(self):
        super().clean()
        self.clean_fields()
        original = _original_evento(self)
        if original is not None:
            _validar_historico_evento(self, original)
            return
        evento = EventoFidelidade.objects.get(pk=self.evento_id)
        if evento.escopo != 'LOJAS':
            raise ValidationError(
                {
                    'evento': 'Evento EMPRESA não aceita relações individuais de Loja.',
                },
            )
        if not Loja.objects.filter(pk=self.loja_id, empresa_id=evento.empresa_id).exists():
            raise ValidationError(
                {'loja': 'A Loja deve pertencer à Empresa do Evento.'},
            )


class AplicacaoEfeitoEventoLote(_RegistroEvento):
    lote = models.ForeignKey(
        LotePontos,
        on_delete=models.PROTECT,
        related_name='aplicacoes_eventos',
    )
    evento = models.ForeignKey(
        EventoFidelidade,
        on_delete=models.PROTECT,
        related_name='aplicacoes_lotes',
    )
    efeito = models.ForeignKey(
        EfeitoEvento,
        on_delete=models.PROTECT,
        related_name='aplicacoes_lotes',
    )
    tipo_aplicado = models.CharField(max_length=20, choices=EfeitoEvento.Tipo.choices)
    valor_aplicado = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        validators=[MinValueValidator(Decimal('0.0001'))],
    )
    criado_em = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['lote', 'tipo_aplicado'],
                name='lote_tipo_evento_unico',
            ),
            models.CheckConstraint(
                condition=models.Q(valor_aplicado__gt=0),
                name='aplicacao_valor_positivo',
            ),
            models.CheckConstraint(
                condition=models.Q(tipo_aplicado='MULTIPLICADOR_PONTOS'),
                name='aplicacao_tipo_suportado',
            ),
        ]

    def clean_fields(self, exclude=None):
        if 'valor_aplicado' not in (exclude or ()) and not isinstance(self.valor_aplicado, Decimal):
            raise ValidationError(
                {
                    'valor_aplicado': 'Informe um Decimal, sem conversão de float.',
                },
            )
        _validar_instantes_evento(self, ('criado_em',), exclude)
        super().clean_fields(exclude=exclude)

    def clean(self):
        super().clean()
        self.clean_fields()
        original = _original_evento(self)
        if original is not None:
            _validar_historico_evento(self, original)
            return  # Cancelamento e configuração atuais não invalidam histórico.
        lote = LotePontos.objects.select_related('compra__loja', 'cliente').get(
            pk=self.lote_id,
        )
        evento = EventoFidelidade.objects.get(pk=self.evento_id)
        efeito = EfeitoEvento.objects.get(pk=self.efeito_id)
        compra = lote.compra
        if (lote.cliente_id != compra.cliente_id or lote.cliente.empresa_id != compra.loja.empresa_id
                or evento.empresa_id != compra.loja.empresa_id or efeito.evento_id != evento.pk):
            raise ValidationError(
                'Lote, Compra, Cliente, Loja, Evento e Efeito devem ser coerentes no mesmo tenant.',
            )
        if self.tipo_aplicado != efeito.tipo or self.valor_aplicado != efeito.valor:
            raise ValidationError('O snapshot deve corresponder ao Efeito aplicado.')
        if self.valor_aplicado != lote.multiplicador_pontos_aplicado:
            raise ValidationError(
                {
                    'valor_aplicado': 'O multiplicador deve coincidir com o snapshot do Lote.',
                },
            )
        if evento.cancelado_em is not None or not evento.inicio_em <= compra.ocorrida_em <= evento.fim_em:
            raise ValidationError('Evento não aplicável à Compra.')
        if evento.escopo == 'LOJAS' and not EventoLoja.objects.filter(evento=evento, loja_id=compra.loja_id).exists():
            raise ValidationError('A Loja não pertence ao escopo do Evento.')


# delete() e QuerySet.delete() também não podem reduzir escopo ou apagar histórico.
@receiver(pre_delete, sender=EventoFidelidade)
@receiver(pre_delete, sender=EventoLoja)
@receiver(pre_delete, sender=EfeitoEvento)
@receiver(pre_delete, sender=AplicacaoEfeitoEventoLote)
def _proteger_historico_eventos(sender, instance, **kwargs):
    from django.db.models.deletion import ProtectedError

    raise ProtectedError(
        'Eventos e aplicações históricas não podem ser excluídos.',
        [instance],
    )


class _HistoricoResgateQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError('Resgates, alocações e estornos são imutáveis.')

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError('Resgates, alocações e estornos são imutáveis.')

    def bulk_create(self, objs, **kwargs):
        raise ValidationError(
            'Use registrar_resgate ou estornar_resgate para criar o histórico completo.',
        )


class _RegistroResgate(models.Model):
    objects = _HistoricoResgateQuerySet.as_manager()

    class Meta:
        abstract = True

    def _original(self):
        if self.pk is None:
            return None
        return type(self)._base_manager.using(self._state.db).filter(pk=self.pk).values().first()

    def _validar_historico(self, original):
        erros = {
            campo.name: 'O fato histórico não pode ser alterado após a criação.'
            for campo in self._meta.fields
            if not campo.primary_key and getattr(self, campo.attname) != original[campo.attname]
        }
        if erros:
            raise ValidationError(erros)

    def save(self, *args, **kwargs):
        from .escrita_resgates import _exigir_escrita_resgates

        if self._original() is None:
            _exigir_escrita_resgates(self)
        # INSERT/constraint arbitra unicidade, inclusive na defesa residual do service.
        self.full_clean(validate_constraints=False)
        return super().save(*args, **kwargs)


class Resgate(_RegistroResgate):
    loja = models.ForeignKey(Loja, on_delete=models.PROTECT, related_name='resgates')
    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.PROTECT,
        related_name='resgates',
    )
    credencial_origem = models.ForeignKey(
        CredencialIntegracao,
        on_delete=models.PROTECT,
        related_name='resgates',
    )
    identificador_externo = models.CharField(max_length=255)
    pontos_resgatados = models.DecimalField(
        max_digits=20,
        decimal_places=0,
        validators=[MinValueValidator(Decimal('1'))],
    )
    resgate_minimo_pontos_aplicado = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    incremento_resgate_pontos_aplicado = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    valor_monetario_por_ponto_aplicado = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    valor_desconto = models.DecimalField(
        max_digits=32,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    resgatado_em = models.DateTimeField(editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['loja', 'identificador_externo'],
                name='resgate_loja_identificador_unico',
            ),
            models.CheckConstraint(
                condition=models.Q(pontos_resgatados__gt=0),
                name='resgate_pontos_positivos',
            ),
            models.CheckConstraint(
                condition=models.Q(resgate_minimo_pontos_aplicado__gt=0),
                name='resgate_minimo_positivo',
            ),
            models.CheckConstraint(
                condition=models.Q(incremento_resgate_pontos_aplicado__gt=0),
                name='resgate_incremento_positivo',
            ),
            models.CheckConstraint(
                condition=models.Q(valor_monetario_por_ponto_aplicado__gt=0),
                name='resgate_taxa_positiva',
            ),
            models.CheckConstraint(
                condition=models.Q(valor_desconto__gt=0),
                name='resgate_desconto_positivo',
            ),
        ]

    def clean_fields(self, exclude=None):
        from .calculos_resgate import normalizar_identificador_resgate

        if 'identificador_externo' not in (exclude or ()):
            self.identificador_externo = normalizar_identificador_resgate(self.identificador_externo)
        for campo in (
            'pontos_resgatados',
            'valor_monetario_por_ponto_aplicado',
            'valor_desconto',
        ):
            valor = getattr(self, campo)
            if campo not in (exclude or ()) and (not isinstance(valor, Decimal) or not valor.is_finite()):
                raise ValidationError(
                    {
                        campo: 'Informe um Decimal finito, sem conversão de float.',
                    },
                )
        for campo in (
            'resgate_minimo_pontos_aplicado',
            'incremento_resgate_pontos_aplicado',
        ):
            if campo not in (exclude or ()) and type(getattr(self, campo)) is not int:
                raise ValidationError({campo: 'Informe um número inteiro.'})
        if 'resgatado_em' not in (exclude or ()):
            if not isinstance(self.resgatado_em, datetime) or timezone.is_naive(self.resgatado_em):
                raise ValidationError(
                    {'resgatado_em': 'Informe uma data/hora com timezone.'},
                )
        super().clean_fields(exclude=exclude)

    def clean(self):
        super().clean()
        self.clean_fields()
        original = self._original()
        if original is not None:
            self._validar_historico(original)
            return
        from apps.empresas.services import exigir_loja_autorizada
        from .calculos_resgate import calcular_desconto

        loja = Loja.objects.get(pk=self.loja_id)
        cliente = Cliente.objects.get(pk=self.cliente_id)
        credencial = CredencialIntegracao.objects.get(pk=self.credencial_origem_id)
        if loja.empresa_id != cliente.empresa_id or loja.empresa_id != credencial.empresa_id:
            raise ValidationError(
                'Loja, Cliente e credencial devem pertencer à mesma Empresa.',
            )
        try:
            exigir_loja_autorizada(credencial, loja)
        except PermissionDenied:
            raise ValidationError(
                {'credencial_origem': 'Credencial não autorizada para a Loja.'},
            ) from None
        pontos = int(self.pontos_resgatados)
        if (pontos < self.resgate_minimo_pontos_aplicado
                or (pontos - self.resgate_minimo_pontos_aplicado) % self.incremento_resgate_pontos_aplicado):
            raise ValidationError(
                {
                    'pontos_resgatados': 'Os pontos devem respeitar o mínimo e incremento aplicados.',
                },
            )
        if self.valor_desconto != calcular_desconto(
            self.pontos_resgatados,
            self.valor_monetario_por_ponto_aplicado,
        ):
            raise ValidationError(
                {
                    'valor_desconto': 'O desconto deve corresponder aos snapshots aplicados.',
                },
            )


class AlocacaoResgate(_RegistroResgate):
    resgate = models.ForeignKey(
        Resgate,
        on_delete=models.PROTECT,
        related_name='alocacoes',
    )
    lote = models.ForeignKey(
        LotePontos,
        on_delete=models.PROTECT,
        related_name='alocacoes_resgate',
    )
    pontos_consumidos = models.DecimalField(
        max_digits=24,
        decimal_places=4,
        validators=[MinValueValidator(Decimal('0.0001'))],
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['resgate', 'lote'],
                name='alocacao_resgate_lote_unico',
            ),
            models.CheckConstraint(
                condition=models.Q(pontos_consumidos__gt=0),
                name='alocacao_pontos_positivos',
            ),
        ]

    def clean_fields(self, exclude=None):
        if 'pontos_consumidos' not in (exclude or ()):
            if not isinstance(self.pontos_consumidos, Decimal) or not self.pontos_consumidos.is_finite():
                raise ValidationError(
                    {
                        'pontos_consumidos': 'Informe um Decimal finito, sem conversão de float.',
                    },
                )
        super().clean_fields(exclude=exclude)

    def clean(self):
        super().clean()
        self.clean_fields()
        original = self._original()
        if original is not None:
            self._validar_historico(original)
            return
        from decimal import Context, localcontext
        from django.db.models import Sum

        resgate = Resgate.objects.select_related('loja', 'cliente').get(
            pk=self.resgate_id,
        )
        lote = LotePontos.objects.select_related('compra__loja').get(pk=self.lote_id)
        if (resgate.cliente_id != lote.cliente_id
                or lote.compra.cliente_id != resgate.cliente_id
                or lote.compra.loja.empresa_id != resgate.loja.empresa_id
                or resgate.cliente.empresa_id != resgate.loja.empresa_id):
            raise ValidationError(
                'Resgate e Lote devem pertencer ao mesmo Cliente e tenant.',
            )
        if lote.expira_em <= resgate.resgatado_em:
            raise ValidationError({'lote': 'Lote expirado no instante do Resgate.'})
        from .consumo import alocacoes_com_consumo_efetivo

        # Os locks já pertencem ao service; não adquirir novos locks em ordem inversa.
        with localcontext(Context(prec=40)):
            consumido = alocacoes_com_consumo_efetivo(type(self).objects.filter(lote_id=lote.pk)).aggregate(
                total=Sum('pontos_consumidos'),
            )['total'] or Decimal('0')
            # Completude do fato original, não saldo: mantém todas as alocações.
            alocado = type(self).objects.filter(resgate_id=resgate.pk).aggregate(
                total=Sum('pontos_consumidos'),
            )['total'] or Decimal('0')
            if consumido + self.pontos_consumidos > lote.pontos_concedidos:
                raise ValidationError(
                    {
                        'pontos_consumidos': 'O consumo excede os pontos concedidos do Lote.',
                    },
                )
            if alocado + self.pontos_consumidos > resgate.pontos_resgatados:
                raise ValidationError(
                    {
                        'pontos_consumidos': 'O consumo excede os pontos do Resgate.',
                    },
                )


class EstornoResgate(_RegistroResgate):
    resgate = models.OneToOneField(Resgate, on_delete=models.PROTECT, related_name='estorno')
    loja = models.ForeignKey(Loja, on_delete=models.PROTECT, related_name='estornos_resgates')
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='estornos_resgates')
    credencial_origem = models.ForeignKey(
        CredencialIntegracao, on_delete=models.PROTECT, related_name='estornos_resgates',
    )
    identificador_externo = models.CharField(max_length=255)
    devolve_pontos_aplicado = models.BooleanField()
    estornado_em = models.DateTimeField(editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['loja', 'identificador_externo'], name='estorno_resgate_loja_identificador_unico',
            ),
        ]

    def clean_fields(self, exclude=None):
        from .calculos_resgate import normalizar_identificador_resgate

        if 'identificador_externo' not in (exclude or ()):
            self.identificador_externo = normalizar_identificador_resgate(self.identificador_externo)
        if 'devolve_pontos_aplicado' not in (exclude or ()) and type(self.devolve_pontos_aplicado) is not bool:
            raise ValidationError({'devolve_pontos_aplicado': 'Informe um booleano.'})
        if 'estornado_em' not in (exclude or ()):
            if not isinstance(self.estornado_em, datetime) or timezone.is_naive(self.estornado_em):
                raise ValidationError({'estornado_em': 'Informe uma data/hora com timezone.'})
        super().clean_fields(exclude=exclude)

    def clean(self):
        super().clean()
        self.clean_fields()
        original = self._original()
        if original is not None:
            self._validar_historico(original)
            return
        from apps.empresas.services import exigir_loja_autorizada

        resgate = Resgate.objects.get(pk=self.resgate_id)
        if (self.loja_id, self.cliente_id) != (resgate.loja_id, resgate.cliente_id):
            raise ValidationError('Loja e Cliente devem corresponder ao Resgate original.')
        try:
            exigir_loja_autorizada(self.credencial_origem, self.loja)
        except PermissionDenied:
            raise ValidationError({'credencial_origem': 'Credencial não autorizada para a Loja.'}) from None


@receiver(pre_delete, sender=EstornoResgate)
@receiver(pre_delete, sender=Resgate)
@receiver(pre_delete, sender=AlocacaoResgate)
def _proteger_historico_resgates(sender, instance, **kwargs):
    from django.db.models.deletion import ProtectedError

    raise ProtectedError(
        'Resgates, alocações e estornos históricos não podem ser excluídos.',
        [instance],
    )


class _NivelFidelidadeQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError('Use os services de Gestão para configurar níveis.')

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError('Use os services de Gestão para configurar níveis.')

    def bulk_create(self, objs, **kwargs):
        raise ValidationError('Use os services de Gestão para configurar níveis.')

    def delete(self):
        raise ValidationError(
            'Use excluir_nivel para preservar a configuração da Empresa.',
        )


class NivelFidelidade(models.Model):
    empresa = models.ForeignKey(
        'empresas.Empresa',
        on_delete=models.PROTECT,
        related_name='niveis_fidelidade',
    )
    # Mesmo limite de Empresa, Loja e EventoFidelidade.
    nome = models.CharField(max_length=255)
    pontos_minimos = models.DecimalField(
        max_digits=24,
        decimal_places=4,
        validators=[MinValueValidator(Decimal('0'))],
    )

    bonus_pontos_percentual = models.DecimalField(
        max_digits=7,
        decimal_places=4,
        default=Decimal("0.0000"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )
    desconto_percentual = models.DecimalField(
        max_digits=7,
        decimal_places=4,
        default=Decimal("0.0000"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )

    objects = _NivelFidelidadeQuerySet.as_manager()

    class Meta:
        ordering = ['pontos_minimos']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    bonus_pontos_percentual__gte=0,
                    bonus_pontos_percentual__lte=100,
                ),
                name="nivel_bonus_percentual_valido",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    desconto_percentual__gte=0,
                    desconto_percentual__lte=100,
                ),
                name="nivel_desconto_percentual_valido",
            ),
            models.UniqueConstraint(
                fields=['empresa', 'pontos_minimos'],
                name='nivel_empresa_threshold_unico',
            ),
            models.CheckConstraint(
                condition=models.Q(pontos_minimos__gte=0),
                name='nivel_threshold_nao_negativo',
            ),
        ]

    def clean_fields(self, exclude=None):
        if 'nome' not in (exclude or ()):
            if not isinstance(self.nome, str) or not self.nome.strip():
                raise ValidationError({'nome': 'Informe um nome textual não vazio.'})
            self.nome = self.nome.strip()
        if 'pontos_minimos' not in (exclude or ()):
            if not isinstance(self.pontos_minimos, Decimal) or not self.pontos_minimos.is_finite():
                raise ValidationError(
                    {'pontos_minimos': 'Informe um Decimal finito, sem float.'},
                )
        for campo in ('bonus_pontos_percentual', 'desconto_percentual'):
            if campo not in (exclude or ()):
                valor = getattr(self, campo)
                if not isinstance(valor, Decimal) or not valor.is_finite():
                    raise ValidationError(
                        {campo: 'Informe um Decimal finito, sem float.'},
                    )
        super().clean_fields(exclude=exclude)

    def clean(self):
        super().clean()
        self.clean_fields()  # full_clean também chama clean após erros de campos.
        if self.pk is not None:
            original = type(self)._base_manager.filter(pk=self.pk).values_list(
                'empresa_id',
                flat=True,
            ).first()
            if original is not None and self.empresa_id != original:
                raise ValidationError(
                    {
                        'empresa': 'A Empresa não pode ser alterada após a criação.',
                    },
                )
        if self.pontos_minimos != 0 and not type(self).objects.filter(
                empresa_id=self.empresa_id, pontos_minimos=0).exclude(
            pk=self.pk,
        ).exists():
            raise ValidationError(
                {
                    'pontos_minimos': 'A configuração deve começar com um nível em zero.',
                },
            )

    def save(self, *args, **kwargs):
        from .escrita_niveis import _exigir_escrita_nivel

        _exigir_escrita_nivel(self)
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        from .escrita_niveis import _exigir_escrita_nivel

        _exigir_escrita_nivel(self)
        return super().delete(*args, **kwargs)

    def __str__(self):
        return self.nome


@receiver(pre_delete, sender=NivelFidelidade)
def _proteger_configuracao_niveis(sender, instance, **kwargs):
    from .escrita_niveis import _exigir_escrita_nivel

    _exigir_escrita_nivel(instance)
