from django import forms
from .formularios import FormularioCompostoMixin

from apps.usuarios.validators import normalizar_cpf, validar_cpf

from .models import ConfiguracaoFidelidadeEmpresa, Loja, MembroEmpresa, OverrideFidelidadeLoja
from .models import CredencialIntegracao
from .services import validar_lojas_credencial

from .validators import normalizar_cnpj, validar_cnpj


class OnboardingEmpresaForm(FormularioCompostoMixin, forms.Form):
    grupos_formulario = (
        ('Empresa', ('nome_empresa', 'cnpj')),
        ('Primeira Loja', ('nome_loja', 'cidade_loja')),
        (
            'Administrador',
            ('cpf', 'first_name', 'last_name', 'senha', 'confirmacao'),
        ),
    )
    cpf = forms.CharField(label="CPF", max_length=32)
    first_name = forms.CharField(
        label="Nome",
        max_length=150,
        required=False,
        help_text="Obrigatório somente para uma nova conta.",
    )
    last_name = forms.CharField(
        label="Sobrenome",
        max_length=150,
        required=False,
        help_text="Obrigatório somente para uma nova conta.",
    )
    senha = forms.CharField(label="Senha", strip=False, widget=forms.PasswordInput)
    confirmacao = forms.CharField(
        label="Confirme a senha",
        strip=False,
        widget=forms.PasswordInput,
    )
    nome_empresa = forms.CharField(label="Nome da Empresa", max_length=255)
    cnpj = forms.CharField(label="CNPJ", max_length=32)
    nome_loja = forms.CharField(label="Nome da primeira Loja", max_length=255)
    cidade_loja = forms.CharField(label="Cidade da primeira Loja", max_length=255)

    def __init__(self, *args, usuario, **kwargs):
        super().__init__(*args, **kwargs)
        if usuario.is_authenticated:
            for campo in ("cpf", "first_name", "last_name", "senha", "confirmacao"):
                self.fields.pop(campo)

    def clean_cnpj(self):
        cnpj = normalizar_cnpj(self.cleaned_data["cnpj"])
        validar_cnpj(cnpj)
        return cnpj


class LojaForm(forms.Form):
    nome = forms.CharField(label="Nome da Loja", max_length=255)
    cidade = forms.CharField(label="Cidade", max_length=255)


class ConviteMembroForm(FormularioCompostoMixin, forms.Form):
    grupos_formulario = (('Pessoa', ('cpf',)), ('Acesso', ('papel', 'lojas')))
    cpf = forms.CharField(label="CPF", max_length=32)
    papel = forms.ChoiceField(label="Papel", choices=MembroEmpresa.Papel.choices)
    lojas = forms.ModelMultipleChoiceField(
        label="Lojas",
        queryset=Loja.objects.none(),
        required=False,
        help_text="Gestor: selecione uma ou mais Lojas. Administrador: deixe vazio.",
    )

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lojas"].queryset = Loja.objects.filter(empresa=empresa).order_by("nome", "pk")

    def clean_cpf(self):
        cpf = normalizar_cpf(self.cleaned_data["cpf"])
        validar_cpf(cpf)
        return cpf

    def clean(self):
        dados = super().clean()
        lojas = dados.get("lojas")
        if dados.get("papel") == MembroEmpresa.Papel.GESTOR and not lojas:
            self.add_error("lojas", "Selecione ao menos uma Loja.")
        if dados.get("papel") == MembroEmpresa.Papel.ADMINISTRADOR and lojas:
            self.add_error(
                "lojas",
                "Administrador tem acesso a todas as Lojas; deixe a seleção vazia.",
            )
        return dados


class AceitarConviteForm(FormularioCompostoMixin, forms.Form):
    grupos_formulario = (
        ('Identificação', ('first_name', 'last_name')),
        ('Acesso', ('senha', 'confirmacao')),
    )
    first_name = forms.CharField(label="Nome", max_length=150, required=False)
    last_name = forms.CharField(label="Sobrenome", max_length=150, required=False)
    senha = forms.CharField(label="Senha", strip=False, widget=forms.PasswordInput)
    confirmacao = forms.CharField(
        label="Confirme a senha",
        strip=False,
        widget=forms.PasswordInput,
        required=False,
    )

    def __init__(self, *args, autenticado, identidade_existente, **kwargs):
        super().__init__(*args, **kwargs)
        if autenticado:
            self.fields.clear()
        elif identidade_existente:
            for campo in ("first_name", "last_name", "confirmacao"):
                self.fields.pop(campo)
        # Nomes e confirmação são exigidos pelo service apenas se a identidade
        # ainda não existir no momento da operação, inclusive após concorrência.


class ConfiguracaoFidelidadeEmpresaForm(FormularioCompostoMixin, forms.ModelForm):
    grupos_formulario = (
        (
            'Acúmulo de pontos',
            (
                'pontos_por_real',
                'precisao_pontos',
                'modo_arredondamento_pontos',
                'modo_aplicacao_nivel',
                'base_calculo_pontos',
            ),
        ),
        (
            'Validade e atividade',
            (
                'validade_pontos_meses',
                'periodo_cliente_ativo_dias',
                'inatividade_suspende_beneficios_nivel',
                'beneficio_primeira_compra_apos_inatividade',
                'promocao_retorno_ativa',
                'bonus_pontos_retorno_percentual',
                'desconto_retorno_percentual',
            ),
        ),
        (
            'Resgate',
            (
                'devolver_pontos_ao_estornar_resgate',
                'resgate_minimo_pontos',
                'incremento_resgate_pontos',
                'valor_monetario_por_ponto',
                'modo_combinacao_descontos_percentuais',
                'ordem_aplicacao_resgate',
            ),
        ),
    )
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        rotulos = {
            'devolver_pontos_ao_estornar_resgate': 'Devolver pontos válidos ao estornar resgate',
            'modo_aplicacao_nivel': 'Nível usado para bônus de pontos',
            'base_calculo_pontos': 'Valor usado para gerar pontos',
            'inatividade_suspende_beneficios_nivel': 'Suspender benefícios de nível durante inatividade',
            'beneficio_primeira_compra_apos_inatividade': 'Benefícios de nível na compra de retorno',
            'promocao_retorno_ativa': 'Ativar promoção de retorno',
            'bonus_pontos_retorno_percentual': 'Bônus de pontos no retorno (%)',
            'desconto_retorno_percentual': 'Desconto no retorno (%)',
            'modo_combinacao_descontos_percentuais': 'Como combinar descontos percentuais',
            'ordem_aplicacao_resgate': 'Quando aplicar o desconto do resgate',
        }
        for nome, rotulo in rotulos.items():
            self.fields[nome].label = rotulo
        self.fields['modo_aplicacao_nivel'].help_text = (
            'O desconto monetário usa sempre o nível anterior à compra.'
        )
        campo = self.fields['modo_arredondamento_pontos']
        campo.label = 'Arredondamento dos pontos'
        campo.choices = [
            ('HALF_UP', 'Mais próximo (5 para cima)'),
            ('DOWN', 'Sempre para baixo'),
            ('UP', 'Sempre para cima'),
        ]

    class Meta:
        model = ConfiguracaoFidelidadeEmpresa
        fields = (
            "pontos_por_real",
            "precisao_pontos",
            "modo_arredondamento_pontos",
            "validade_pontos_meses",
            "devolver_pontos_ao_estornar_resgate",
            "resgate_minimo_pontos",
            "incremento_resgate_pontos",
            "valor_monetario_por_ponto",
            "periodo_cliente_ativo_dias",
            "modo_aplicacao_nivel",
            "base_calculo_pontos",
            "inatividade_suspende_beneficios_nivel",
            "beneficio_primeira_compra_apos_inatividade",
            "promocao_retorno_ativa",
            "bonus_pontos_retorno_percentual",
            "desconto_retorno_percentual",
            "modo_combinacao_descontos_percentuais",
            "ordem_aplicacao_resgate",
        )


class OverrideFidelidadeLojaForm(forms.ModelForm):
    class Meta:
        model = OverrideFidelidadeLoja
        fields = ("pontos_por_real",)


class CredencialIntegracaoForm(FormularioCompostoMixin, forms.Form):
    grupos_formulario = (('Identificação', ('nome',)), ('Acesso', ('escopo', 'lojas')))
    nome = forms.CharField(label="Nome", max_length=255)
    escopo = forms.ChoiceField(
        label="Aplicação",
        choices=[('EMPRESA', 'Toda a empresa'), ('LOJAS', 'Lojas específicas')],
    )
    lojas = forms.ModelMultipleChoiceField(
        label="Lojas",
        queryset=Loja.objects.none(),
        required=False,
        help_text="Selecione uma ou mais lojas para aplicação em lojas específicas. Para toda a empresa, deixe vazio.",
    )

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        self.fields["lojas"].queryset = Loja.objects.filter(empresa=empresa).order_by("nome", "pk")

    def clean(self):
        dados = super().clean()
        if "escopo" in dados and "lojas" in dados:
            validar_lojas_credencial(
                self.empresa,
                dados["escopo"],
                dados["lojas"],
            )
        return dados
