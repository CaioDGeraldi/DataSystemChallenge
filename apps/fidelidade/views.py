from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.empresas.services import exigir_administrador

from .eventos import cancelar_evento, criar_evento
from .forms import EventoFidelidadeForm, NivelFidelidadeForm
from .models import EfeitoEvento, EventoFidelidade
from .niveis import criar_nivel, editar_nivel, excluir_nivel, listar_niveis, nivel_para_gestao


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


@login_required
@require_GET
def niveis(request):
    membro = exigir_administrador(request)
    return render(request, 'datasystem/gestor/niveis.html', {
        'empresa': membro.empresa, 'niveis': listar_niveis(request),
    })


@login_required
@require_http_methods(['GET', 'POST'])
def novo_nivel(request):
    exigir_administrador(request)
    form = NivelFidelidadeForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        try:
            criar_nivel(request, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        else:
            messages.success(request, 'Nível criado.')
            return redirect('fidelidade:niveis')
    return render(request, 'datasystem/formulario.html', {
        'form': form, 'titulo': 'Criar nível de fidelidade', 'botao': 'Criar nível',
    })


@login_required
@require_http_methods(['GET', 'POST'])
def editar_nivel_view(request, nivel_id):
    nivel = nivel_para_gestao(request, nivel_id)
    form = NivelFidelidadeForm(request.POST if request.method == 'POST' else None,
                              initial={'nome': nivel.nome, 'pontos_minimos': nivel.pontos_minimos})
    if request.method == 'POST' and form.is_valid():
        try:
            editar_nivel(request, nivel_id, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        else:
            messages.success(request, 'Nível atualizado. A classificação atual usa os novos limites.')
            return redirect('fidelidade:niveis')
    return render(request, 'datasystem/formulario.html', {
        'form': form, 'titulo': 'Editar nível de fidelidade', 'botao': 'Salvar nível',
    })


@login_required
@require_POST
def excluir_nivel_view(request, nivel_id):
    try:
        excluir_nivel(request, nivel_id)
    except ValidationError as exc:
        messages.error(request, ' '.join(exc.messages))
    else:
        messages.success(request, 'Nível excluído.')
    return redirect('fidelidade:niveis')
