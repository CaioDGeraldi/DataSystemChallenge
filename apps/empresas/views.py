from dataclasses import asdict

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django.views.decorators.cache import never_cache
from django.urls import reverse

from apps.usuarios.services import validar_contexto_ativo

from .apresentacao import contexto_gestao

from .forms import (
    AceitarConviteForm,
    ConfiguracaoFidelidadeEmpresaForm,
    ConviteMembroForm,
    CredencialIntegracaoForm,
    LojaForm,
    OnboardingEmpresaForm,
    OverrideFidelidadeLojaForm,
)
from .models import ConviteMembro, CredencialIntegracao, MembroEmpresa
from .services import criar_credencial, desativar_credencial
from .services import (
    consultar_configuracao_loja, remover_override_loja, resolver_configuracao,
    salvar_configuracao_empresa, salvar_override_loja,
)
from .services import (
    aceitar_convite, concluir_onboarding, criar_convite, criar_loja_no_contexto,
    exigir_administrador, localizar_convite, resolver_lojas_visiveis, revogar_convite,
)


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
        "form": form, "titulo": "Criar Empresa e primeira Loja", "botao": "Criar empresa", "ilustracao_onboarding": True
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
        **contexto_gestao(membro, 'lojas', 'Nova Loja'),
        "form": form, "titulo": f"Nova Loja — {membro.empresa}", "botao": "Criar Loja"
    })


@login_required
@require_GET
def area(request):
    membro = validar_contexto_ativo(request, "gestao")
    return render(request, "datasystem/gestor/area.html", {
        **contexto_gestao(membro, 'lojas'),
        "membro": membro, "lojas": resolver_lojas_visiveis(request),
        "pode_criar_loja": membro.papel == MembroEmpresa.Papel.ADMINISTRADOR,
    })


@login_required
@require_GET
def membros(request):
    administrador = exigir_administrador(request)
    return render(request, "datasystem/gestor/membros.html", {
        **contexto_gestao(administrador, 'membros'),
        "empresa": administrador.empresa,
        "membros": MembroEmpresa.objects.filter(empresa_id=administrador.empresa_id).select_related("usuario").order_by("pk"),
        "convites": ConviteMembro.objects.filter(empresa_id=administrador.empresa_id).order_by("-criado_em"),
    })


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def convidar_membro(request):
    administrador = exigir_administrador(request)
    form = ConviteMembroForm(
        request.POST if request.method == "POST" else None, empresa=administrador.empresa,
    )
    if request.method == "POST" and form.is_valid():
        try:
            convite, token = criar_convite(request, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        else:
            resposta = render(request, "datasystem/gestor/convite_criado.html", {
                **contexto_gestao(administrador, 'membros', 'Convite criado'),
                "convite": convite,
                "url_aceite": request.build_absolute_uri(reverse("empresas:aceitar_convite", args=[token])),
            })
            resposta["Referrer-Policy"] = "no-referrer"
            return resposta
    return render(request, "datasystem/formulario.html", {
        **contexto_gestao(administrador, 'membros', 'Convidar membro'),
        "form": form, "titulo": f"Convidar membro — {administrador.empresa}", "botao": "Criar convite",
    })


@never_cache
@sensitive_post_parameters("senha", "confirmacao")
@require_http_methods(["GET", "POST"])
def aceitar_convite_view(request, token):
    convite = localizar_convite(token)
    if request.user.is_authenticated and request.user.cpf != convite.cpf:
        raise PermissionDenied("Entre com a identidade destinatária deste convite.")
    form = AceitarConviteForm(
        request.POST if request.method == "POST" else None,
        autenticado=request.user.is_authenticated,
        identidade_existente=get_user_model().objects.filter(cpf=convite.cpf).exists(),
    )
    if request.method == "POST" and form.is_valid():
        try:
            aceitar_convite(request, token, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        else:
            return redirect("empresas:area")
    resposta = render(request, "datasystem/convites/aceitar.html", {"form": form, "convite": convite})
    resposta["Referrer-Policy"] = "no-referrer"
    return resposta


@login_required
@require_POST
def revogar_convite_view(request, convite_id):
    try:
        revogar_convite(request, convite_id)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "Convite revogado.")
    return redirect("empresas:membros")


@login_required
@require_http_methods(["GET", "POST"])
def configuracao_empresa(request):
    membro = exigir_administrador(request)
    efetiva = resolver_configuracao(membro.empresa)
    form = ConfiguracaoFidelidadeEmpresaForm(
        request.POST if request.method == "POST" else None, initial=asdict(efetiva),
    )
    if request.method == "POST" and form.is_valid():
        try:
            salvar_configuracao_empresa(request, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        else:
            messages.success(request, "Configuração da Empresa salva.")
            return redirect("empresas:configuracao_empresa")
    return render(request, "datasystem/formulario.html", {
        **contexto_gestao(membro, 'configuracao'),
        "form": form, "titulo": f"Configuração de fidelidade — {membro.empresa}", "botao": "Salvar configuração",
    })


@login_required
@require_http_methods(["GET", "POST"])
def configuracao_loja(request, loja_id):
    if "loja_id" in request.POST and request.POST["loja_id"] != str(loja_id):
        raise PermissionDenied("Loja divergente da URL autorizada.")
    contexto = consultar_configuracao_loja(request, loja_id)
    membro = exigir_administrador(request)
    form = OverrideFidelidadeLojaForm(
        request.POST if request.method == "POST" else None,
        initial={"pontos_por_real": contexto["configuracao"].pontos_por_real},
    )
    if request.method == "POST" and form.is_valid():
        try:
            salvar_override_loja(request, loja_id, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        else:
            messages.success(request, "Configuração específica da Loja salva.")
            return redirect("empresas:configuracao_loja", loja_id=loja_id)
    return render(request, "datasystem/gestor/configuracao_loja.html", {
        **contexto_gestao(membro, 'lojas', f"Configuração — {contexto['loja'].nome}"), **contexto, "form": form,
    })


@login_required
@require_POST
def remover_override_loja_view(request, loja_id):
    if "loja_id" in request.POST and request.POST["loja_id"] != str(loja_id):
        raise PermissionDenied("Loja divergente da URL autorizada.")
    remover_override_loja(request, loja_id)
    messages.success(request, "A Loja voltou a usar a configuração da Empresa.")
    return redirect("empresas:configuracao_loja", loja_id=loja_id)


@login_required
@never_cache
@require_GET
def integracoes(request):
    administrador = exigir_administrador(request)
    credenciais = CredencialIntegracao.objects.filter(empresa_id=administrador.empresa_id).order_by(
        "-criada_em", "-pk",
    ).values("id", "nome", "identificador", "escopo", "ativa", "criada_em", "ultimo_uso_em")
    return render(request, "datasystem/gestor/integracoes.html", {
        **contexto_gestao(administrador, 'integracoes'),
        "empresa": administrador.empresa, "credenciais": credenciais,
    })


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
@sensitive_variables()
def nova_integracao(request):
    administrador = exigir_administrador(request)
    form = CredencialIntegracaoForm(
        request.POST if request.method == "POST" else None, empresa=administrador.empresa,
    )
    if request.method == "POST" and form.is_valid():
        try:
            credencial, chave = criar_credencial(request, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        else:
            resposta = render(request, "datasystem/gestor/integracao_criada.html", {
                **contexto_gestao(administrador, 'integracoes', 'Chave de integração criada'),
                "nome": credencial.nome, "chave": chave,
            })
            resposta["Referrer-Policy"] = "no-referrer"
            return resposta
    return render(request, "datasystem/gestor/integracao_form.html", {
        **contexto_gestao(administrador, 'integracoes', 'Criar chave de integração'), "form": form,
    })


@login_required
@require_POST
def desativar_integracao(request, credencial_id):
    desativar_credencial(request, credencial_id)
    messages.success(request, "Chave de integração desativada.")
    return redirect("empresas:integracoes")
