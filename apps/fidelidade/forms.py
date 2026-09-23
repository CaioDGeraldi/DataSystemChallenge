from decimal import Decimal

from django import forms

from apps.empresas.models import Loja

from .eventos import validar_escopo_evento
from .models import EventoFidelidade


class EventoFidelidadeForm(forms.Form):
    nome = forms.CharField(label='Nome', max_length=255)
    descricao = forms.CharField(label='Descrição', required=False, widget=forms.Textarea)
    inicio_em = forms.DateTimeField(label='Início', widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'))
    fim_em = forms.DateTimeField(label='Fim', widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'))
    escopo = forms.ChoiceField(label='Escopo', choices=EventoFidelidade.Escopo.choices)
    lojas = forms.ModelMultipleChoiceField(label='Lojas', queryset=Loja.objects.none(), required=False,
                                          help_text='EMPRESA: deixe vazio. LOJAS: selecione uma ou mais.')
    multiplicador = forms.DecimalField(label='Multiplicador de pontos', max_digits=12, decimal_places=4,
                                      min_value=Decimal('0.0001'), help_text='Ex.: 2.0000 para conceder o dobro dos pontos.')

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        self.fields['lojas'].queryset = Loja.objects.filter(empresa=empresa).order_by('nome', 'pk')

    def clean(self):
        dados = super().clean()
        if 'escopo' in dados and 'lojas' in dados:
            validar_escopo_evento(self.empresa, dados['escopo'], dados['lojas'])
        return dados
