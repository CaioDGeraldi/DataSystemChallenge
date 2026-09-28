from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_GET, require_POST

from apps.empresas.models import Empresa
from apps.usuarios.services import trocar_programa_cliente, validar_contexto_ativo

from .consultas import apresentar_compra, compras_cliente, resgates_cliente, resumo_cliente
from .forms import CadastroClienteForm
from .models import Cliente
from .services import cadastrar_cliente


@sensitive_post_parameters("senha", "confirmacao")
@require_http_methods(["GET", "POST"])
def cadastro(request, slug):
    empresa = get_object_or_404(Empresa, slug=slug)
    form = CadastroClienteForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            cadastrar_cliente(empresa=empresa, request=request, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        else:
            messages.success(request, "Vínculo de Cliente confirmado. Entre com seu CPF e senha.")
            return redirect("usuarios:login")
    return render(request, "datasystem/formulario.html", {
        "form": form, "titulo": f"Cadastro de Cliente — {empresa}", "botao": "Confirmar cadastro"
    })


@login_required
@require_GET
def area(request):
    cliente = validar_contexto_ativo(request, "cliente")
    return render(request, "datasystem/cliente/area.html", {
        **_contexto(cliente, "inicio"), **resumo_cliente(cliente),
    })


def _contexto(cliente, pagina):
    return {
        'cliente': cliente, 'pagina': pagina,
        'programas': Cliente.objects.filter(usuario_id=cliente.usuario_id).select_related('empresa').order_by('empresa__nome', 'pk'),
    }


@login_required
@require_GET
def pontos(request):
    cliente = validar_contexto_ativo(request, 'cliente')
    pagina = Paginator(compras_cliente(cliente), 10).get_page(request.GET.get('page'))
    pagina.object_list = [apresentar_compra(compra) for compra in pagina.object_list]
    return render(request, 'datasystem/cliente/pontos.html', {**_contexto(cliente, 'pontos'), 'historico': pagina})


@login_required
@require_GET
def resgates(request):
    cliente = validar_contexto_ativo(request, 'cliente')
    pagina = Paginator(resgates_cliente(cliente), 10).get_page(request.GET.get('page'))
    return render(request, 'datasystem/cliente/resgates.html', {**_contexto(cliente, 'resgates'), 'historico': pagina})


@login_required
@require_POST
def trocar_programa(request):
    if request.POST.get('tipo_contexto', 'cliente') != 'cliente':
        raise PermissionDenied('Escolha um dos seus programas.')
    trocar_programa_cliente(request, request.POST.get('cliente_id'))
    return redirect('clientes:area')
