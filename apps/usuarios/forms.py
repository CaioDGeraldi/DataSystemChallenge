from django import forms
from django.contrib.auth import authenticate


class LoginForm(forms.Form):
    cpf = forms.CharField(label="CPF", max_length=32)
    senha = forms.CharField(label="Senha", strip=False, widget=forms.PasswordInput)

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.usuario = None

    def clean(self):
        dados = super().clean()
        if "cpf" in dados and "senha" in dados:
            self.usuario = authenticate(self.request, cpf=dados["cpf"], password=dados["senha"])
            if self.usuario is None:
                raise forms.ValidationError("CPF ou senha inválidos.")
        return dados


class SelecaoContextoForm(forms.Form):
    contexto = forms.ChoiceField(label="Contexto", widget=forms.RadioSelect)

    def __init__(self, contextos, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["contexto"].choices = [
            (f"{c['tipo_contexto']}:{c['vinculo_id']}", c["titulo"]) for c in contextos
        ]
