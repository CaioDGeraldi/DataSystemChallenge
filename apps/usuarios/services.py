from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

from apps.clientes.models import Cliente
from apps.empresas.models import MembroEmpresa

from .validators import normalizar_cpf, validar_cpf

CONTEXTO_SESSAO = "contexto_ativo"


def _usuario_valido(usuario):
    return usuario.is_authenticated and get_user_model().objects.filter(pk=usuario.pk, is_active=True).exists()


def resolver_contextos(usuario):
    if not _usuario_valido(usuario):
        return []
    contextos = []
    for tipo, vinculos in (
        ("cliente", Cliente.objects.filter(usuario=usuario)),
        ("gestao", MembroEmpresa.objects.filter(usuario=usuario, ativo=True)),
    ):
        for vinculo in vinculos.select_related("empresa").order_by("empresa__nome", "pk"):
            titulo = f"Cliente — {vinculo.empresa}" if tipo == "cliente" else f"Gestão — {vinculo.empresa} ({vinculo.get_papel_display()})"
            contextos.append({"tipo_contexto": tipo, "empresa_id": vinculo.empresa_id,
                              "vinculo_id": vinculo.pk, "titulo": titulo})
    return contextos


def _buscar_vinculo(usuario, tipo, vinculo_id, empresa_id=None):
    if not _usuario_valido(usuario) or tipo not in ("cliente", "gestao"):
        raise PermissionDenied("Contexto não autorizado.")
    try:
        filtros = {"pk": int(vinculo_id), "usuario_id": usuario.pk}
        if empresa_id is not None:
            filtros["empresa_id"] = int(empresa_id)
    except (TypeError, ValueError, OverflowError):
        raise PermissionDenied("Contexto inválido.") from None
    model = Cliente if tipo == "cliente" else MembroEmpresa
    if tipo == "gestao":
        filtros["ativo"] = True
    vinculo = model.objects.select_related("empresa").filter(**filtros).first()
    if vinculo is None:
        raise PermissionDenied("Contexto não autorizado.")
    return vinculo


def ativar_contexto(request, tipo, vinculo_id):
    if CONTEXTO_SESSAO in request.session:
        raise PermissionDenied("Encerre a sessão antes de selecionar outro contexto.")
    vinculo = _buscar_vinculo(request.user, tipo, vinculo_id)
    request.session[CONTEXTO_SESSAO] = {
        "tipo_contexto": tipo, "empresa_id": vinculo.empresa_id, "vinculo_id": vinculo.pk
    }
    return "clientes:area" if tipo == "cliente" else "empresas:area"


def validar_contexto_ativo(request, tipo=None):
    contexto = request.session.get(CONTEXTO_SESSAO)
    try:
        if not isinstance(contexto, dict) or set(contexto) != {"tipo_contexto", "empresa_id", "vinculo_id"}:
            raise PermissionDenied("Selecione um contexto autorizado.")
        if any(type(contexto[chave]) is not int for chave in ("empresa_id", "vinculo_id")):
            raise PermissionDenied("Contexto inválido.")
        vinculo = _buscar_vinculo(request.user, contexto["tipo_contexto"], contexto["vinculo_id"], contexto["empresa_id"])
    except PermissionDenied:
        request.session.pop(CONTEXTO_SESSAO, None)
        raise
    if tipo is not None and contexto["tipo_contexto"] != tipo:
        raise PermissionDenied("O contexto ativo não permite acessar esta área.")
    return vinculo


def resolver_identidade(*, cpf, senha, confirmacao, first_name="", last_name="", request=None):
    """Cria ou autentica identidade; participa da transação do caso de uso chamador."""
    cpf = normalizar_cpf(cpf)
    validar_cpf(cpf)
    if not senha or senha != confirmacao:
        raise ValidationError("A senha e a confirmação devem coincidir e não podem estar vazias.")
    Usuario = get_user_model()
    with transaction.atomic():
        usuario = Usuario.objects.select_for_update().filter(cpf=cpf).first()
        novo = False
        if usuario is None:
            first_name, last_name = first_name.strip(), last_name.strip()
            if not first_name or not last_name:
                raise ValidationError("Nome e sobrenome são obrigatórios para uma nova identidade.")
            candidato = Usuario(cpf=cpf, first_name=first_name, last_name=last_name)
            validate_password(senha, candidato)
            try:
                # Savepoint: uma disputa pelo CPF não invalida a transação externa.
                with transaction.atomic():
                    usuario = Usuario.objects.create_user(
                        cpf, senha, first_name=first_name, last_name=last_name
                    )
                novo = True
            except (IntegrityError, ValidationError):
                usuario = Usuario.objects.select_for_update().filter(cpf=cpf).first()
                if usuario is None:
                    raise
        if not novo:
            autenticado = authenticate(request, cpf=cpf, password=senha)
            if autenticado is None or autenticado.pk != usuario.pk:
                raise ValidationError("Não foi possível autenticar com o CPF e a senha informados.")
            usuario = autenticado
        return usuario


def trocar_programa_cliente(request, vinculo_id):
    """Exceção restrita Cliente → Cliente, sem ampliar ativar_contexto."""
    validar_contexto_ativo(request, 'cliente')
    vinculo = _buscar_vinculo(request.user, 'cliente', vinculo_id)
    request.session[CONTEXTO_SESSAO] = {
        'tipo_contexto': 'cliente', 'empresa_id': vinculo.empresa_id, 'vinculo_id': vinculo.pk,
    }
