from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods

from apps.usuarios.services import validar_contexto_ativo

from .forms import LojaForm, OnboardingEmpresaForm
from .models import MembroEmpresa
from .services import concluir_onboarding, criar_loja_no_contexto, exigir_administrador, resolver_lojas_visiveis


@sensitive_post_parameters("senha", "confirmacao")
@require_http_methods(["GET", "POST"])
def onboarding(request):
    form = OnboardingEmpresaForm(
        request.POST if request.method == "POST" else None, usuario=request.user
    )
    if request.method == "POST" and form.is_valid():
        try:
            concluir_onboarding(request, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        else:
            return redirect("empresas:area")
    return render(request, "datasystem/formulario.html", {
        "form": form, "titulo": "Criar Empresa e primeira Loja", "botao": "Concluir onboarding"
    })


@login_required
@require_http_methods(["GET", "POST"])
def criar_loja(request):
    membro = exigir_administrador(request)
    form = LojaForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            criar_loja_no_contexto(request, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        else:
            messages.success(request, "Loja criada.")
            return redirect("empresas:area")
    return render(request, "datasystem/formulario.html", {
        "form": form, "titulo": f"Nova Loja — {membro.empresa}", "botao": "Criar Loja"
    })


@login_required
@require_GET
def area(request):
    membro = validar_contexto_ativo(request, "gestao")
    return render(request, "datasystem/gestor/area.html", {
        "membro": membro, "lojas": resolver_lojas_visiveis(request),
        "pode_criar_loja": membro.papel == MembroEmpresa.Papel.ADMINISTRADOR,
    })
