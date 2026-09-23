from django.core.exceptions import ValidationError as DomainValidationError
from rest_framework.exceptions import ValidationError
from rest_framework.views import exception_handler as drf_exception_handler


ERROS = {
    400: ("requisicao_invalida", "Dados inválidos."),
    401: ("credencial_invalida", "Credencial de integração inválida."),
    403: ("acesso_negado", "Acesso negado."),
    404: ("nao_encontrado", "Recurso não encontrado."),
    405: ("metodo_nao_permitido", "Método não permitido."),
    406: ("formato_nao_aceito", "Formato de resposta não aceito."),
    415: ("formato_nao_suportado", "Formato de conteúdo não suportado."),
    500: ("erro_interno", "Erro interno do servidor."),
}


def envelope_erro(status):
    codigo, mensagem = ERROS.get(status, ("erro_api", "Não foi possível concluir a requisição."))
    return {"erro": {"codigo": codigo, "mensagem": mensagem}}


def exception_handler(exc, context):
    if isinstance(exc, DomainValidationError):
        exc = ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages)
    resposta = drf_exception_handler(exc, context)
    if resposta is None:
        # O DRF relança a exceção: preserva logging, reporting e rollback do Django.
        # Em produção (DEBUG=False), o Django serve a resposta 500 genérica.
        return None
    dados = envelope_erro(resposta.status_code)
    if isinstance(exc, ValidationError):
        dados["erro"]["detalhes"] = resposta.data
    resposta.data = dados
    return resposta
