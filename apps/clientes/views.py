from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_GET

from apps.empresas.models import Empresa
from apps.usuarios.services import validar_contexto_ativo

from .forms import CadastroClienteForm
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
    return render(request, "datasystem/cliente/area.html", {"cliente": cliente})
