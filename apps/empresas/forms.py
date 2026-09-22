from django import forms

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
