from django.contrib.auth import login as autenticar_sessao, logout as encerrar_sessao
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST

from .forms import LoginForm, SelecaoContextoForm
from .services import CONTEXTO_SESSAO, ativar_contexto, resolver_contextos, validar_contexto_ativo


def _area_ativa(request):
    validar_contexto_ativo(request)
    return "clientes:area" if request.session[CONTEXTO_SESSAO]["tipo_contexto"] == "cliente" else "empresas:area"


@sensitive_post_parameters("senha")
@require_http_methods(["GET", "POST"])
def login(request):
    if request.user.is_authenticated:
        return redirect(_area_ativa(request) if CONTEXTO_SESSAO in request.session else "usuarios:selecionar_contexto")
    form = LoginForm(request.POST if request.method == "POST" else None, request=request)
    if request.method == "POST" and form.is_valid():
        contextos = resolver_contextos(form.usuario)
        if not contextos:
            raise PermissionDenied("Credenciais válidas, mas nenhum contexto está autorizado para esta conta.")
        autenticar_sessao(request, form.usuario)
        request.session.pop(CONTEXTO_SESSAO, None)
        if len(contextos) == 1:
            contexto = contextos[0]
            return redirect(ativar_contexto(request, contexto["tipo_contexto"], contexto["vinculo_id"]))
        return redirect("usuarios:selecionar_contexto")
    return render(request, "datasystem/formulario.html", {
        "form": form, "titulo": "Entrar", "botao": "Entrar", "mostrar_onboarding": True,
    })


@login_required
@require_http_methods(["GET", "POST"])
def selecionar_contexto(request):
    if CONTEXTO_SESSAO in request.session:
        return redirect(_area_ativa(request))
    contextos = resolver_contextos(request.user)
    if not contextos:
        raise PermissionDenied("Nenhum contexto está autorizado para esta conta.")
    form = SelecaoContextoForm(contextos, request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        tipo, vinculo_id = form.cleaned_data["contexto"].split(":")
        return redirect(ativar_contexto(request, tipo, vinculo_id))
    return render(request, "datasystem/formulario.html", {"form": form, "titulo": "Selecionar contexto", "botao": "Continuar"})


@require_POST
def logout(request):
    encerrar_sessao(request)
    return redirect("usuarios:login")


@require_http_methods(["GET"])
def home(request):
    """Orientação pública e apresentação dos contextos já autorizados."""
    contextos = []
    contexto_ativo = None
    if request.user.is_authenticated:
        contextos = resolver_contextos(request.user)
        if CONTEXTO_SESSAO in request.session:
            try:
                validar_contexto_ativo(request)
            except PermissionDenied:
                # O validador existente remove contexto inválido/obsoleto.
                pass
            else:
                contexto_ativo = request.session[CONTEXTO_SESSAO]
        for contexto in contextos:
            contexto["ativo"] = contexto_ativo == {
                chave: contexto[chave]
                for chave in ("tipo_contexto", "empresa_id", "vinculo_id")
            }
            contexto["destino"] = (
                "clientes:area" if contexto["tipo_contexto"] == "cliente" else "empresas:area"
            )
    return render(request, "datasystem/home.html", {
        "contextos": contextos, "contexto_ativo": contexto_ativo,
        "titulo": "Retorna",
    })


@require_http_methods(["GET"])
def para_empresas(request):
    return render(request, "datasystem/para_empresas.html", {"titulo": "Retorna para empresas"})
