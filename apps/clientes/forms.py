from django import forms


class CadastroClienteForm(forms.Form):
    cpf = forms.CharField(label="CPF", max_length=32)
    first_name = forms.CharField(label="Nome", max_length=150, required=False,
                                 help_text="Obrigatório somente para uma nova conta.")
    last_name = forms.CharField(label="Sobrenome", max_length=150, required=False,
                                help_text="Obrigatório somente para uma nova conta.")
    senha = forms.CharField(label="Senha", strip=False, widget=forms.PasswordInput)
    confirmacao = forms.CharField(label="Confirme a senha", strip=False, widget=forms.PasswordInput)
