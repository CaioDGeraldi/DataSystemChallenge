from django import forms

from apps.usuarios.validators import normalizar_cpf, validar_cpf

from .models import ConfiguracaoFidelidadeEmpresa, Loja, MembroEmpresa, OverrideFidelidadeLoja

from .validators import normalizar_cnpj, validar_cnpj


class OnboardingEmpresaForm(forms.Form):
    cpf = forms.CharField(label="CPF", max_length=32)
    first_name = forms.CharField(label="Nome", max_length=150, required=False,
                                 help_text="Obrigatório somente para uma nova conta.")
    last_name = forms.CharField(label="Sobrenome", max_length=150, required=False,
                                help_text="Obrigatório somente para uma nova conta.")
    senha = forms.CharField(label="Senha", strip=False, widget=forms.PasswordInput)
    confirmacao = forms.CharField(label="Confirme a senha", strip=False, widget=forms.PasswordInput)
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


class ConviteMembroForm(forms.Form):
    cpf = forms.CharField(label="CPF", max_length=32)
    papel = forms.ChoiceField(label="Papel", choices=MembroEmpresa.Papel.choices)
    lojas = forms.ModelMultipleChoiceField(
        label="Lojas", queryset=Loja.objects.none(), required=False,
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
            self.add_error("lojas", "Administrador não recebe escopo por Loja.")
        return dados


class AceitarConviteForm(forms.Form):
    first_name = forms.CharField(label="Nome", max_length=150, required=False)
    last_name = forms.CharField(label="Sobrenome", max_length=150, required=False)
    senha = forms.CharField(label="Senha", strip=False, widget=forms.PasswordInput)
    confirmacao = forms.CharField(label="Confirme a senha", strip=False, widget=forms.PasswordInput, required=False)

    def __init__(self, *args, autenticado, identidade_existente, **kwargs):
        super().__init__(*args, **kwargs)
        if autenticado:
            self.fields.clear()
        elif identidade_existente:
            for campo in ("first_name", "last_name", "confirmacao"):
                self.fields.pop(campo)
        # Nomes e confirmação são exigidos pelo service apenas se a identidade
        # ainda não existir no momento da operação, inclusive após concorrência.


class ConfiguracaoFidelidadeEmpresaForm(forms.ModelForm):
    class Meta:
        model = ConfiguracaoFidelidadeEmpresa
        fields = (
            "pontos_por_real", "validade_pontos_meses", "resgate_minimo_pontos",
            "incremento_resgate_pontos", "valor_monetario_por_ponto", "periodo_cliente_ativo_dias",
        )


class OverrideFidelidadeLojaForm(forms.ModelForm):
    class Meta:
        model = OverrideFidelidadeLoja
        fields = ("pontos_por_real",)
