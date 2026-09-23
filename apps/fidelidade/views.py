from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.empresas.services import exigir_administrador

from .eventos import cancelar_evento, criar_evento
from .forms import EventoFidelidadeForm
from .models import EfeitoEvento, EventoFidelidade


@login_required
@require_GET
def eventos(request):
    membro = exigir_administrador(request)
    registros = EventoFidelidade.objects.filter(empresa_id=membro.empresa_id).prefetch_related(
        'efeitos', 'lojas_selecionadas__loja',
    ).order_by('-inicio_em', '-pk')
    return render(request, 'datasystem/gestor/eventos.html', {'empresa': membro.empresa, 'eventos': registros})


@login_required
@require_http_methods(['GET', 'POST'])
def novo_evento(request):
    membro = exigir_administrador(request)
    form = EventoFidelidadeForm(request.POST if request.method == 'POST' else None, empresa=membro.empresa)
    if request.method == 'POST' and form.is_valid():
        dados = dict(form.cleaned_data)
        multiplicador = dados.pop('multiplicador')
        try:
            criar_evento(request, **dados, efeitos=[{'tipo': EfeitoEvento.Tipo.MULTIPLICADOR_PONTOS, 'valor': multiplicador}])
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        else:
            messages.success(request, 'Evento criado.')
            return redirect('fidelidade:eventos')
    return render(request, 'datasystem/formulario.html', {'form': form, 'titulo': 'Criar Evento de fidelidade', 'botao': 'Criar Evento'})


@login_required
@require_POST
def cancelar_evento_view(request, evento_id):
    cancelar_evento(request, evento_id)
    messages.success(request, 'Evento cancelado. O histórico concedido foi preservado.')
    return redirect('fidelidade:eventos')
