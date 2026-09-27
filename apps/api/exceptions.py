from django.core.exceptions import ValidationError as DomainValidationError
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.views import exception_handler as drf_exception_handler

from apps.fidelidade.exceptions import ResgateNaoEncontrado, ResgateJaEstornado, ResgateVinculadoCompra, LimiteResgateExcedido
from apps.fidelidade.exceptions import ClienteNaoEncontrado, IdempotenciaConflitante, LojaForaDoEscopo
from apps.fidelidade.exceptions import IncrementoResgateInvalido, PontosAbaixoDoMinimo, SaldoInsuficiente


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
    erros_fidelidade = {
        ResgateVinculadoCompra: (409, 'resgate_vinculado_compra', 'Resgate já vinculado a uma Compra.'),
        LimiteResgateExcedido: (400, 'limite_resgate_excedido', 'Desconto do Resgate excede o máximo aplicável à Compra.'),
        ResgateNaoEncontrado: (404, "resgate_nao_encontrado", "Resgate não encontrado."),
        ResgateJaEstornado: (409, "resgate_ja_estornado", "Resgate já estornado."),
        PontosAbaixoDoMinimo: (400, 'pontos_abaixo_do_minimo', 'Pontos abaixo do mínimo para Resgate.'),
        IncrementoResgateInvalido: (400, 'incremento_resgate_invalido', 'Pontos incompatíveis com o incremento de Resgate.'),
        SaldoInsuficiente: (400, 'saldo_insuficiente', 'Saldo insuficiente para Resgate.'),
        LojaForaDoEscopo: (403, "loja_fora_do_escopo", "Loja não autorizada para esta integração."),
        ClienteNaoEncontrado: (404, "cliente_nao_encontrado", "Cliente não encontrado."),
        IdempotenciaConflitante: (409, "idempotencia_conflitante", "Identificador externo já utilizado com dados diferentes."),
    }
    erro_fidelidade = erros_fidelidade.get(type(exc))
    if erro_fidelidade is not None:
        status, codigo, mensagem = erro_fidelidade
        exc = APIException(detail=mensagem, code=codigo)
        exc.status_code = status
    if isinstance(exc, DomainValidationError):
        exc = ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages)
    resposta = drf_exception_handler(exc, context)
    if resposta is None:
        # O DRF relança a exceção: preserva logging, reporting e rollback do Django.
        # Em produção (DEBUG=False), o Django serve a resposta 500 genérica.
        return None
    dados = envelope_erro(resposta.status_code)
    if erro_fidelidade is not None:
        dados = {"erro": {"codigo": codigo, "mensagem": mensagem}}
    if isinstance(exc, ValidationError):
        dados["erro"]["detalhes"] = resposta.data
    resposta.data = dados
    return resposta
