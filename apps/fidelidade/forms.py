from decimal import Decimal

from django import forms

from apps.empresas.models import Loja
from apps.empresas.formularios import FormularioCompostoMixin

from .eventos import validar_escopo_evento
from .models import EventoFidelidade


class EventoFidelidadeForm(FormularioCompostoMixin, forms.Form):
    grupos_formulario = (
        ('Campanha', ('nome', 'descricao', 'inicio_em', 'fim_em')),
        ('Aplicação', ('escopo', 'lojas')),
        ('Pontuação', ('multiplicador',)),
    )
    nome = forms.CharField(label='Nome', max_length=255)
    descricao = forms.CharField(label='Descrição', required=False, widget=forms.Textarea)
    inicio_em = forms.DateTimeField(label='Início', widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'))
    fim_em = forms.DateTimeField(label='Fim', widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'))
    escopo = forms.ChoiceField(label='Aplicação', choices=[('EMPRESA', 'Toda a empresa'), ('LOJAS', 'Lojas específicas')],
                              widget=forms.Select(attrs={'data-campaign-application': ''}))
    lojas = forms.ModelMultipleChoiceField(label='Lojas', queryset=Loja.objects.none(), required=False,
                                          widget=forms.CheckboxSelectMultiple(attrs={'class': 'retorna-store-choices'}),
                                          help_text='Selecione uma ou mais lojas quando a aplicação for em lojas específicas.')
    multiplicador = forms.DecimalField(label='Multiplicador de pontos', max_digits=12, decimal_places=4,
                                      min_value=Decimal('0.0001'), help_text='1,00 = pontos normais; 1,50 = 50% a mais; 2,00 = dobro de pontos.')

    selecao_lojas_campanha = True

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        self.fields['lojas'].queryset = Loja.objects.filter(empresa=empresa).order_by('nome', 'pk')
        self.fields['lojas'].label_from_instance = lambda loja: f'{loja.nome} — {loja.cidade}'

    def clean(self):
        dados = super().clean()
        if 'escopo' in dados and 'lojas' in dados:
            validar_escopo_evento(self.empresa, dados['escopo'], dados['lojas'])
        return dados


class NivelFidelidadeForm(forms.Form):
    nome = forms.CharField(label='Nome', max_length=255, strip=True)
    pontos_minimos = forms.DecimalField(
        label='Pontos mínimos', max_digits=24, decimal_places=4, min_value=Decimal('0'),
        help_text='Total histórico de pontos concedidos. O primeiro nível deve começar em zero.',
    )
