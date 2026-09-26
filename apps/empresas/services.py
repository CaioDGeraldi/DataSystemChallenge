from dataclasses import asdict

import hashlib
import re
import secrets

from django.contrib.auth import authenticate, get_user_model, login
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils.text import slugify
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from apps.usuarios.validators import normalizar_cpf, validar_cpf

from apps.usuarios.services import (
    CONTEXTO_SESSAO, ativar_contexto, resolver_identidade, validar_contexto_ativo,
)

from .models import AcessoLoja, ConviteAcessoLoja, ConviteMembro, Empresa, Loja, MembroEmpresa
from .validators import normalizar_cnpj, validar_cnpj
from .models import ConfiguracaoFidelidadeEmpresa, OverrideFidelidadeLoja
from .models import CredencialAcessoLoja, CredencialIntegracao, _permitir_acessos_iniciais
from .parametros import ConfiguracaoEfetiva, PADROES_FIDELIDADE


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
                raise ValidationError(
                    {"cnpj": "Já existe uma Empresa com este CNPJ."},
                ) from exc
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


def concluir_onboarding(
    request,
    *,
    nome_empresa,
    cnpj,
    nome_loja,
    cidade_loja,
    cpf="",
    first_name="",
    last_name="",
    senha="",
    confirmacao="",
):
    with transaction.atomic():
        if request.user.is_authenticated:
            usuario = get_user_model().objects.select_for_update().filter(
                pk=request.user.pk,
                is_active=True,
            ).first()
            if usuario is None:
                raise PermissionDenied("A conta não está ativa.")
        else:
            usuario = resolver_identidade(
                request=request,
                cpf=cpf,
                senha=senha,
                confirmacao=confirmacao,
                first_name=first_name,
                last_name=last_name,
            )
        empresa = _criar_empresa(nome_empresa, cnpj)
        _criar_loja(empresa, nome_loja, cidade_loja)
        membro = MembroEmpresa.objects.create(
            usuario=usuario,
            empresa=empresa,
            papel=MembroEmpresa.Papel.ADMINISTRADOR,
            ativo=True,
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
        raise PermissionDenied("Esta operação exige um Administrador.")
    return membro


def criar_loja_no_contexto(request, *, nome, cidade):
    with transaction.atomic():
        contexto = exigir_administrador(request)
        membro = MembroEmpresa.objects.select_for_update().filter(
            pk=contexto.pk,
            usuario_id=request.user.pk,
            empresa_id=contexto.empresa_id,
            ativo=True,
            papel=MembroEmpresa.Papel.ADMINISTRADOR,
        ).first()
        if membro is None:
            raise PermissionDenied(
                "O vínculo administrativo não está mais disponível.",
            )
        return _criar_loja(membro.empresa, nome, cidade)


def resolver_lojas_visiveis(request):
    membro = validar_contexto_ativo(request, "gestao")
    lojas = Loja.objects.filter(empresa_id=membro.empresa_id)
    if membro.papel == MembroEmpresa.Papel.GESTOR:
        lojas = lojas.filter(acessos_membros__membro_id=membro.pk)
    elif membro.papel != MembroEmpresa.Papel.ADMINISTRADOR:
        raise PermissionDenied("Papel não autorizado.")
    return lojas.order_by("nome", "pk")


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _administrador_bloqueado(request):
    contexto = exigir_administrador(request)
    membro = MembroEmpresa.objects.select_for_update().filter(
        pk=contexto.pk,
        usuario_id=request.user.pk,
        empresa_id=contexto.empresa_id,
        ativo=True,
        papel=MembroEmpresa.Papel.ADMINISTRADOR,
    ).first()
    if membro is None:
        raise PermissionDenied("Vínculo administrativo indisponível.")
    return membro


def criar_convite(request, *, cpf, papel, lojas=()):
    cpf = normalizar_cpf(cpf)
    validar_cpf(cpf)
    with transaction.atomic():
        contexto = exigir_administrador(request)
        # Serializa convites da Empresa, inclusive quando ainda não há convite
        # para o CPF. NO KEY UPDATE permite inserções de FKs durante aceites.
        Empresa.objects.select_for_update(no_key=True).get(
            pk=contexto.empresa_id,
        )
        criador = _administrador_bloqueado(request)
        ids = {loja.pk for loja in lojas}
        selecionadas = list(Loja.objects.filter(pk__in=ids, empresa_id=criador.empresa_id))
        if len(selecionadas) != len(ids):
            raise ValidationError("Todas as Lojas devem pertencer à Empresa ativa.")
        if papel not in MembroEmpresa.Papel.values:
            raise ValidationError("Papel inválido.")
        if papel == MembroEmpresa.Papel.ADMINISTRADOR and ids:
            raise ValidationError("Administrador não recebe escopo por Loja.")
        if papel == MembroEmpresa.Papel.GESTOR and not ids:
            raise ValidationError("Selecione ao menos uma Loja para o Gestor.")
        if MembroEmpresa.objects.filter(
            empresa_id=criador.empresa_id,
            usuario__cpf=cpf,
        ).exists():
            raise ValidationError("Este CPF já possui vínculo com a Empresa.")
        if ConviteMembro.objects.filter(
            empresa_id=criador.empresa_id,
            cpf=cpf,
            aceito_em__isnull=True,
            revogado_em__isnull=True,
            expira_em__gt=timezone.now(),
        ).exists():
            raise ValidationError(
                "Já existe convite pendente para este CPF nesta Empresa.",
            )
        token = secrets.token_urlsafe(32)
        convite = ConviteMembro.objects.create(
            empresa_id=criador.empresa_id,
            criado_por=criador,
            cpf=cpf,
            papel=papel,
            token_hash=hash_token(token),
        )
        for loja in selecionadas:
            ConviteAcessoLoja.objects.create(convite=convite, loja=loja)
        return convite, token


def _exigir_convite_pendente(convite):
    if convite is None or convite.estado != "pendente":
        raise PermissionDenied("Convite indisponível ou inválido.")
    return convite


def localizar_convite(token):
    return _exigir_convite_pendente(
        ConviteMembro.objects.select_related("empresa").filter(token_hash=hash_token(token)).first(),
    )


def _identidade_do_convite(
    request,
    convite,
    *,
    senha="",
    confirmacao="",
    first_name="",
    last_name="",
):
    Usuario = get_user_model()
    usuario = Usuario.objects.select_for_update().filter(cpf=convite.cpf).first()
    if request.user.is_authenticated:
        if (usuario is None or usuario.pk != request.user.pk
                or request.user.cpf != convite.cpf or not usuario.is_active):
            raise PermissionDenied(
                "Entre com a identidade destinatária deste convite.",
            )
        return usuario
    if usuario is not None:
        # Aceite de identidade existente solicita somente senha, sem confirmação.
        autenticado = authenticate(request, cpf=convite.cpf, password=senha)
        if autenticado is None or autenticado.pk != usuario.pk:
            raise ValidationError(
                "Não foi possível autenticar com a senha informada.",
            )
        return autenticado
    # Somente a criação usa a semântica de nome, senha e confirmação. O helper
    # também trata uma identidade criada concorrentemente antes do INSERT.
    return resolver_identidade(
        request=request,
        cpf=convite.cpf,
        senha=senha,
        confirmacao=confirmacao,
        first_name=first_name,
        last_name=last_name,
    )


def aceitar_convite(request, token, **identidade):
    with transaction.atomic():
        convite = _exigir_convite_pendente(
            ConviteMembro.objects.select_for_update().filter(token_hash=hash_token(token)).first(),
        )
        usuario = _identidade_do_convite(request, convite, **identidade)
        if MembroEmpresa.objects.filter(
            usuario=usuario,
            empresa_id=convite.empresa_id,
        ).exists():
            raise ValidationError("Esta identidade já possui vínculo com a Empresa.")
        escopos = list(convite.acessos_lojas.select_related("loja"))
        if convite.papel == MembroEmpresa.Papel.GESTOR:
            if not escopos or any(e.loja.empresa_id != convite.empresa_id for e in escopos):
                raise ValidationError(
                    "O convite deve possuir Lojas válidas da própria Empresa.",
                )
        elif convite.papel != MembroEmpresa.Papel.ADMINISTRADOR or escopos:
            raise ValidationError("Papel ou escopo de convite inválido.")
        membro = MembroEmpresa.objects.create(
            usuario=usuario,
            empresa_id=convite.empresa_id,
            papel=convite.papel,
            ativo=True,
        )
        for escopo in escopos:
            AcessoLoja.objects.create(membro=membro, loja=escopo.loja)
        convite.aceito_em = timezone.now()
        convite.save(update_fields=["aceito_em"])

    # Exceção restrita ao vínculo que este aceite acabou de criar para o alvo.
    if not request.user.is_authenticated:
        login(request, usuario)
    anterior = request.session.pop(CONTEXTO_SESSAO, None)
    try:
        ativar_contexto(request, "gestao", membro.pk)
    except PermissionDenied:
        if anterior is not None:
            request.session[CONTEXTO_SESSAO] = anterior
        raise
    return membro


def revogar_convite(request, convite_id):
    with transaction.atomic():
        contexto = exigir_administrador(request)
        convite = ConviteMembro.objects.select_for_update().filter(
            pk=convite_id,
            empresa_id=contexto.empresa_id,
        ).first()
        _administrador_bloqueado(request)
        if convite is None:
            raise PermissionDenied("Convite não autorizado.")
        if not convite.pode_revogar:
            raise ValidationError("Somente convites pendentes podem ser revogados.")
        convite.revogado_em = timezone.now()
        convite.save(update_fields=["revogado_em"])
        return convite


def resolver_configuracao(empresa, loja=None):
    if empresa.pk is None or not Empresa.objects.filter(pk=empresa.pk).exists():
        raise ValidationError("Informe uma Empresa persistida.")
    if loja is not None:
        if (loja.empresa_id != empresa.pk or loja.pk is None
                or not Loja.objects.filter(pk=loja.pk, empresa_id=empresa.pk).exists()):
            raise ValidationError("A Loja deve pertencer à Empresa informada.")
    corporativa = ConfiguracaoFidelidadeEmpresa.objects.filter(empresa_id=empresa.pk).first()
    valores = asdict(PADROES_FIDELIDADE)
    if corporativa is not None:
        valores = {campo: getattr(corporativa, campo) for campo in valores}
    if loja is not None:
        override = OverrideFidelidadeLoja.objects.filter(loja_id=loja.pk).first()
        if override is not None:
            valores["pontos_por_real"] = override.pontos_por_real
    return ConfiguracaoEfetiva(
        empresa_id=empresa.pk,
        loja_id=loja.pk if loja is not None else None,
        **valores,
    )


def salvar_configuracao_empresa(
    request,
    *,
    pontos_por_real,
    validade_pontos_meses,
    resgate_minimo_pontos,
    incremento_resgate_pontos,
    valor_monetario_por_ponto,
    periodo_cliente_ativo_dias,
    precisao_pontos,
    modo_arredondamento_pontos,
    devolver_pontos_ao_estornar_resgate=None,
    inatividade_suspende_beneficios_nivel=None,
    promocao_retorno_ativa=None,
    beneficio_primeira_compra_apos_inatividade=None,
    modo_combinacao_descontos_percentuais=None,
    ordem_aplicacao_resgate=None,
    base_calculo_pontos=None,
    modo_aplicacao_nivel=None,
    bonus_pontos_retorno_percentual=None,
    desconto_retorno_percentual=None,
):
    with transaction.atomic():
        contexto = exigir_administrador(request)
        # O lock da Empresa também serializa a primeira edição, sem linha prévia.
        empresa = Empresa.objects.select_for_update(no_key=True).get(
            pk=contexto.empresa_id,
        )
        _administrador_bloqueado(request)
        configuracao = ConfiguracaoFidelidadeEmpresa.objects.filter(empresa=empresa).first()
        if configuracao is None:
            configuracao = ConfiguracaoFidelidadeEmpresa(empresa=empresa)
        if devolver_pontos_ao_estornar_resgate is not None:
            configuracao.devolver_pontos_ao_estornar_resgate = devolver_pontos_ao_estornar_resgate
        configuracao.precisao_pontos = precisao_pontos
        configuracao.modo_arredondamento_pontos = modo_arredondamento_pontos
        configuracao.pontos_por_real = pontos_por_real
        configuracao.validade_pontos_meses = validade_pontos_meses
        configuracao.resgate_minimo_pontos = resgate_minimo_pontos
        configuracao.incremento_resgate_pontos = incremento_resgate_pontos
        configuracao.valor_monetario_por_ponto = valor_monetario_por_ponto
        configuracao.periodo_cliente_ativo_dias = periodo_cliente_ativo_dias
        if inatividade_suspende_beneficios_nivel is not None:
            configuracao.inatividade_suspende_beneficios_nivel = (
                inatividade_suspende_beneficios_nivel
            )
        if promocao_retorno_ativa is not None:
            configuracao.promocao_retorno_ativa = promocao_retorno_ativa
        if beneficio_primeira_compra_apos_inatividade is not None:
            configuracao.beneficio_primeira_compra_apos_inatividade = (
                beneficio_primeira_compra_apos_inatividade
            )
        if modo_combinacao_descontos_percentuais is not None:
            configuracao.modo_combinacao_descontos_percentuais = (
                modo_combinacao_descontos_percentuais
            )
        if ordem_aplicacao_resgate is not None:
            configuracao.ordem_aplicacao_resgate = ordem_aplicacao_resgate
        if base_calculo_pontos is not None:
            configuracao.base_calculo_pontos = base_calculo_pontos
        if modo_aplicacao_nivel is not None:
            configuracao.modo_aplicacao_nivel = modo_aplicacao_nivel
        if bonus_pontos_retorno_percentual is not None:
            configuracao.bonus_pontos_retorno_percentual = (
                bonus_pontos_retorno_percentual
            )
        if desconto_retorno_percentual is not None:
            configuracao.desconto_retorno_percentual = (
                desconto_retorno_percentual
            )
        configuracao.save()
        return configuracao


def loja_para_configuracao(request, loja_id):
    membro = exigir_administrador(request)
    loja = Loja.objects.filter(pk=loja_id, empresa_id=membro.empresa_id).select_related(
        "empresa",
    ).first()
    if loja is None:
        raise PermissionDenied("Loja não autorizada neste contexto.")
    return loja


def salvar_override_loja(request, loja_id, *, pontos_por_real):
    with transaction.atomic():
        _administrador_bloqueado(request)
        loja = loja_para_configuracao(request, loja_id)
        Loja.objects.select_for_update().get(pk=loja.pk)
        override = OverrideFidelidadeLoja.objects.filter(loja=loja).first()
        if override is None:
            override = OverrideFidelidadeLoja(loja=loja)
        override.pontos_por_real = pontos_por_real
        override.save()
        return override


def remover_override_loja(request, loja_id):
    with transaction.atomic():
        _administrador_bloqueado(request)
        loja = loja_para_configuracao(request, loja_id)
        Loja.objects.select_for_update().get(pk=loja.pk)
        OverrideFidelidadeLoja.objects.filter(loja=loja).delete()


def consultar_configuracao_loja(request, loja_id):
    loja = loja_para_configuracao(request, loja_id)
    return {
        "loja": loja,
        "configuracao": resolver_configuracao(loja.empresa, loja),
        "tem_override": OverrideFidelidadeLoja.objects.filter(loja=loja).exists(),
    }


@sensitive_variables()
def gerar_chave_integracao():
    """Identificador público (144 bits) e segredo (256 bits), independentes."""
    return secrets.token_urlsafe(18), secrets.token_urlsafe(32)


def validar_lojas_credencial(empresa, escopo, lojas):
    if escopo not in CredencialIntegracao.Escopo.values:
        raise ValidationError({"escopo": "Escopo inválido."})
    ids = {loja.pk for loja in lojas}
    if escopo == CredencialIntegracao.Escopo.EMPRESA and ids:
        raise ValidationError(
            {"lojas": "Credencial EMPRESA não recebe seleção de Lojas."},
        )
    if escopo == CredencialIntegracao.Escopo.LOJAS and not ids:
        raise ValidationError({"lojas": "Selecione ao menos uma Loja."})
    selecionadas = list(
        Loja.objects.filter(pk__in=ids, empresa_id=empresa.pk).order_by(
            "nome",
            "pk",
        ),
    )
    if len(selecionadas) != len(ids):
        raise ValidationError(
            {"lojas": "Todas as Lojas devem pertencer à Empresa ativa."},
        )
    return selecionadas


@sensitive_variables()
def criar_credencial(request, *, nome, escopo, lojas=()):
    with transaction.atomic():
        criador = _administrador_bloqueado(request)
        selecionadas = validar_lojas_credencial(criador.empresa, escopo, lojas)
        identificador, segredo = gerar_chave_integracao()
        credencial = CredencialIntegracao.objects.create(
            empresa_id=criador.empresa_id,
            criada_por=criador,
            nome=nome,
            identificador=identificador,
            segredo_hash=make_password(segredo),
            escopo=escopo,
        )
        with _permitir_acessos_iniciais(credencial, selecionadas):
            for loja in selecionadas:
                CredencialAcessoLoja.objects.create(
                    credencial=credencial,
                    loja=loja,
                )
        # A chave é um retorno efêmero, nunca atributo do model ou dado de sessão.
        return credencial, f"{identificador}.{segredo}"


def desativar_credencial(request, credencial_id):
    with transaction.atomic():
        administrador = _administrador_bloqueado(request)
        credencial = CredencialIntegracao.objects.select_for_update().filter(
            pk=credencial_id,
            empresa_id=administrador.empresa_id,
        ).first()
        if credencial is None:
            raise PermissionDenied("Credencial não autorizada neste contexto.")
        credencial.ativa = False
        credencial.save(update_fields=["ativa"])
        return credencial


@sensitive_variables()
def autenticar_credencial(chave):
    """Retorna a credencial válida ou None, sem distinguir falhas publicamente."""
    if not isinstance(chave, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}\.[A-Za-z0-9_-]{1,128}", chave):
        return None
    identificador, segredo = chave.split(".")
    with transaction.atomic():
        # O mesmo lock da desativação evita restaurar estado obsoleto ao registrar uso.
        credencial = CredencialIntegracao.objects.select_for_update().filter(
            identificador=identificador,
        ).first()
        if credencial is None:
            # Custo do hasher também para identificadores inexistentes.
            make_password(segredo)
            return None
        segredo_valido = check_password(segredo, credencial.segredo_hash)
        if not segredo_valido or not credencial.ativa:
            return None
        credencial.ultimo_uso_em = timezone.now()
        credencial.save(update_fields=["ultimo_uso_em"])
        return credencial


def lojas_autorizadas(credencial):
    # Reconsulta estado persistido: objetos antigos ou adulterados não ampliam acesso.
    atual = CredencialIntegracao.objects.filter(pk=credencial.pk, ativa=True).first()
    if atual is None:
        return Loja.objects.none()
    lojas = Loja.objects.filter(empresa_id=atual.empresa_id)
    if atual.escopo == CredencialIntegracao.Escopo.LOJAS:
        lojas = lojas.filter(acessos_credenciais__credencial_id=atual.pk)
    elif atual.escopo != CredencialIntegracao.Escopo.EMPRESA:
        return Loja.objects.none()
    return lojas.order_by("nome", "pk")


def exigir_loja_autorizada(credencial, loja):
    autorizada = lojas_autorizadas(credencial).filter(pk=loja.pk).first()
    if autorizada is None:
        raise PermissionDenied("Loja não autorizada para esta integração.")
    return autorizada
