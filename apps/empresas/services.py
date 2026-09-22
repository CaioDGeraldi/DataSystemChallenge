from django.contrib.auth import get_user_model, login
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils.text import slugify

from apps.usuarios.services import (
    CONTEXTO_SESSAO, ativar_contexto, resolver_identidade, validar_contexto_ativo,
)

from .models import Empresa, Loja, MembroEmpresa
from .validators import normalizar_cnpj, validar_cnpj


def gerar_slug_disponivel(nome):
    limite = Empresa._meta.get_field("slug").max_length
    base = slugify(nome)[:limite] or "empresa"
    slug = base
    numero = 2
    while Empresa.objects.filter(slug=slug).exists():
        sufixo = f"-{numero}"
        slug = base[:limite - len(sufixo)] + sufixo
        numero += 1
    return slug


def _criar_empresa(nome, cnpj):
    cnpj = normalizar_cnpj(cnpj)
    validar_cnpj(cnpj)
    while True:
        slug = gerar_slug_disponivel(nome)
        try:
            # O índice único resolve disputas posteriores à escolha do slug.
            with transaction.atomic():
                return Empresa.objects.create(nome=nome, cnpj=cnpj, slug=slug)
        except (IntegrityError, ValidationError) as exc:
            if Empresa.objects.filter(cnpj=cnpj).exists():
                raise ValidationError({"cnpj": "Já existe uma Empresa com este CNPJ."}) from exc
            colisao_slug = Empresa.objects.filter(slug=slug).exists()
            erro_de_slug = isinstance(exc, IntegrityError) or (
                hasattr(exc, "message_dict") and set(exc.message_dict) == {"slug"}
            )
            if not colisao_slug or not erro_de_slug:
                raise


def _criar_loja(empresa, nome, cidade):
    loja = Loja(empresa=empresa, nome=nome, cidade=cidade)
    loja.full_clean()
    loja.save()
    return loja


def concluir_onboarding(request, *, nome_empresa, cnpj, nome_loja, cidade_loja,
                        cpf="", first_name="", last_name="", senha="", confirmacao=""):
    with transaction.atomic():
        if request.user.is_authenticated:
            usuario = get_user_model().objects.select_for_update().filter(
                pk=request.user.pk, is_active=True
            ).first()
            if usuario is None:
                raise PermissionDenied("A conta não está ativa.")
        else:
            usuario = resolver_identidade(
                request=request, cpf=cpf, senha=senha, confirmacao=confirmacao,
                first_name=first_name, last_name=last_name,
            )
        empresa = _criar_empresa(nome_empresa, cnpj)
        _criar_loja(empresa, nome_loja, cidade_loja)
        membro = MembroEmpresa.objects.create(
            usuario=usuario, empresa=empresa,
            papel=MembroEmpresa.Papel.ADMINISTRADOR, ativo=True,
        )

    if not request.user.is_authenticated:
        login(request, usuario)
    # Exceção restrita: somente o vínculo recém-criado neste onboarding pode
    # substituir o contexto anterior. Não recebe um vínculo escolhido no POST.
    anterior = request.session.pop(CONTEXTO_SESSAO, None)
    try:
        ativar_contexto(request, "gestao", membro.pk)
    except PermissionDenied:
        if anterior is not None:
            request.session[CONTEXTO_SESSAO] = anterior
        raise
    return membro


def exigir_administrador(request):
    membro = validar_contexto_ativo(request, "gestao")
    if membro.papel != MembroEmpresa.Papel.ADMINISTRADOR:
        raise PermissionDenied("Somente Administradores podem criar Lojas.")
    return membro


def criar_loja_no_contexto(request, *, nome, cidade):
    with transaction.atomic():
        contexto = exigir_administrador(request)
        membro = MembroEmpresa.objects.select_for_update().filter(
            pk=contexto.pk, usuario_id=request.user.pk, empresa_id=contexto.empresa_id,
            ativo=True, papel=MembroEmpresa.Papel.ADMINISTRADOR,
        ).first()
        if membro is None:
            raise PermissionDenied("O vínculo administrativo não está mais disponível.")
        return _criar_loja(membro.empresa, nome, cidade)


def resolver_lojas_visiveis(request):
    membro = validar_contexto_ativo(request, "gestao")
    lojas = Loja.objects.filter(empresa_id=membro.empresa_id)
    if membro.papel == MembroEmpresa.Papel.GESTOR:
        lojas = lojas.filter(acessos_membros__membro_id=membro.pk)
    elif membro.papel != MembroEmpresa.Papel.ADMINISTRADOR:
        raise PermissionDenied("Papel não autorizado.")
    return lojas.order_by("nome", "pk")
