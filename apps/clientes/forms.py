from django import forms
from apps.empresas.formularios import FormularioCompostoMixin


class CadastroClienteForm(FormularioCompostoMixin, forms.Form):
    grupos_formulario = (('Identificação', ('cpf', 'first_name', 'last_name')), ('Acesso', ('senha', 'confirmacao')))
    cpf = forms.CharField(label="CPF", max_length=32)
    first_name = forms.CharField(label="Nome", max_length=150, required=False,
                                 help_text="Obrigatório somente para uma nova conta.")
    last_name = forms.CharField(label="Sobrenome", max_length=150, required=False,
                                help_text="Obrigatório somente para uma nova conta.")
    senha = forms.CharField(label="Senha", strip=False, widget=forms.PasswordInput)
    confirmacao = forms.CharField(label="Confirme a senha", strip=False, widget=forms.PasswordInput)
