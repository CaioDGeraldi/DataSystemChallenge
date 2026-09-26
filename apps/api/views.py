from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.empresas.services import lojas_autorizadas
from apps.fidelidade.consultas import consultar_fidelidade_cliente
from apps.fidelidade.services import registrar_compra
from apps.fidelidade.simulacoes import simular_compra
from apps.fidelidade.resgates import registrar_resgate

from .exceptions import envelope_erro
from .serializers import ContextoSerializer, EnvelopeErroSerializer, HealthSerializer
from .serializers import ConsultaFidelidadeQuerySerializer, FidelidadeClienteSerializer
from .serializers import CompraSerializer, RegistrarCompraSerializer
from .serializers import SimularCompraSerializer, SimulacaoCompraSerializer
from .serializers import RegistrarResgateSerializer, ResgateSerializer


class HealthView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    http_method_names = ["get", "head", "options"]

    @extend_schema(auth=[], responses={200: HealthSerializer, 405: EnvelopeErroSerializer})
    def get(self, request):
        return Response({"status": "ok"})


@method_decorator(never_cache, name="dispatch")
class ContextoView(APIView):
    http_method_names = ["get", "head", "options"]

    @extend_schema(responses={200: ContextoSerializer, 401: EnvelopeErroSerializer, 405: EnvelopeErroSerializer})
    def get(self, request):
        credencial = request.auth
        dados = {
            "credencial": credencial,
            "empresa": credencial.empresa,
            "escopo": credencial.escopo,
            "lojas": lojas_autorizadas(credencial),
        }
        return Response(ContextoSerializer(dados).data)


@method_decorator(never_cache, name="dispatch")
class ConsultaFidelidadeView(APIView):
    http_method_names = ["get", "head", "options"]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="loja_id",
                type=int,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Loja em que o PDV está operando.",
            ),
            OpenApiParameter(
                name="cliente_cpf",
                type=str,
                location=OpenApiParameter.QUERY,
                required=True,
                description="CPF do Cliente da Empresa da Loja.",
            ),
        ],
        responses={
            200: FidelidadeClienteSerializer,
            400: OpenApiResponse(
                EnvelopeErroSerializer,
                description="requisicao_invalida",
            ),
            401: OpenApiResponse(
                EnvelopeErroSerializer,
                description="credencial_invalida",
            ),
            403: OpenApiResponse(
                EnvelopeErroSerializer,
                description="loja_fora_do_escopo",
            ),
            404: OpenApiResponse(
                EnvelopeErroSerializer,
                description="cliente_nao_encontrado",
            ),
            405: OpenApiResponse(
                EnvelopeErroSerializer,
                description="metodo_nao_permitido",
            ),
        },
        description=(
            "Consulta o estado atual de fidelidade do Cliente para o PDV. "
            "Não persiste snapshots; operações posteriores recalculam o estado."
        ),
    )
    def get(self, request):
        entrada = ConsultaFidelidadeQuerySerializer(data=request.query_params)
        entrada.is_valid(raise_exception=True)
        dados = consultar_fidelidade_cliente(
            credencial=request.auth,
            **entrada.validated_data,
        )
        return Response(FidelidadeClienteSerializer(dados).data)


@method_decorator(never_cache, name="dispatch")
class SimulacaoCompraView(APIView):
    http_method_names = ["post", "options"]

    @extend_schema(
        request=SimularCompraSerializer,
        responses={
            200: SimulacaoCompraSerializer,
            400: OpenApiResponse(
                EnvelopeErroSerializer,
                description="requisicao_invalida",
            ),
            401: OpenApiResponse(
                EnvelopeErroSerializer,
                description="credencial_invalida",
            ),
            403: OpenApiResponse(
                EnvelopeErroSerializer,
                description="loja_fora_do_escopo",
            ),
            404: OpenApiResponse(
                EnvelopeErroSerializer,
                description="cliente_nao_encontrado",
            ),
            405: OpenApiResponse(
                EnvelopeErroSerializer,
                description="metodo_nao_permitido",
            ),
        },
        description=(
            "Simula os efeitos atuais de fidelidade de uma Compra sem "
            "persistir operação, snapshot ou reserva de estado."
        ),
    )
    def post(self, request):
        entrada = SimularCompraSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)

        dados = simular_compra(
            credencial=request.auth,
            **entrada.validated_data,
        )

        return Response(SimulacaoCompraSerializer(dados).data)


@method_decorator(never_cache, name="dispatch")
class CompraView(APIView):
    http_method_names = ["post", "options"]

    @extend_schema(
        request=RegistrarCompraSerializer,
        responses={
            201: OpenApiResponse(CompraSerializer, description="Compra e LotePontos criados atomicamente."),
            200: OpenApiResponse(CompraSerializer, description="Retry preserva Compra e fidelidade originais; legado sem Lote retorna fidelidade null."),
            400: OpenApiResponse(EnvelopeErroSerializer, description="requisicao_invalida"),
            401: OpenApiResponse(EnvelopeErroSerializer, description="credencial_invalida"),
            403: OpenApiResponse(EnvelopeErroSerializer, description="loja_fora_do_escopo"),
            404: OpenApiResponse(EnvelopeErroSerializer, description="cliente_nao_encontrado"),
            409: OpenApiResponse(EnvelopeErroSerializer, description="idempotencia_conflitante"),
            405: OpenApiResponse(EnvelopeErroSerializer, description="metodo_nao_permitido"),
        },
        description=("Registra Compra e fidelidade atomicamente. Idempotência por Loja + identificador externo. "
                     "Aplica a configuração efetiva no processamento e campanha em ocorrida_em antes do arredondamento. "
                     "Preserva snapshots nos retries. "
                     "Expiração ou pontos não representáveis retornam 400 com rollback integral."),
    )
    def post(self, request):
        entrada = RegistrarCompraSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        compra, criada = registrar_compra(credencial=request.auth, **entrada.validated_data)
        return Response(CompraSerializer(compra).data, status=201 if criada else 200)


@method_decorator(never_cache, name='dispatch')
class ResgateView(APIView):
    http_method_names = ['post', 'options']

    @extend_schema(
        request=RegistrarResgateSerializer,
        responses={
            201: OpenApiResponse(ResgateSerializer, description='Resgate e alocações criados atomicamente.'),
            200: OpenApiResponse(ResgateSerializer, description='Retry retorna histórico original, sem recalcular ou consumir novamente.'),
            400: OpenApiResponse(EnvelopeErroSerializer, description='requisicao_invalida, pontos_abaixo_do_minimo, incremento_resgate_invalido ou saldo_insuficiente'),
            401: OpenApiResponse(EnvelopeErroSerializer, description='credencial_invalida'),
            403: OpenApiResponse(EnvelopeErroSerializer, description='loja_fora_do_escopo'),
            404: OpenApiResponse(EnvelopeErroSerializer, description='cliente_nao_encontrado'),
            409: OpenApiResponse(EnvelopeErroSerializer, description='idempotencia_conflitante'),
            405: OpenApiResponse(EnvelopeErroSerializer, description='metodo_nao_permitido'),
        },
        description=('Resgate idempotente por Loja + identificador externo. Pontos inteiros positivos; '
                     'mínimo e (pontos - mínimo) % incremento == 0. Consumo FEFO por expiração, aquisição e pk. '
                     'Instante exclusivo do servidor, sem campos adicionais ou backdating; expira_em deve ser estritamente maior. '
                     'Desconto em centavos com HALF_UP e snapshots históricos. Retry não consulta configuração nem saldo.'),
    )
    def post(self, request):
        entrada = RegistrarResgateSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        resgate, criado = registrar_resgate(credencial=request.auth, **entrada.validated_data)
        return Response(ResgateSerializer(resgate).data, status=201 if criado else 200)


@csrf_exempt
def nao_encontrado(request, caminho):
    # Também cobre falhas do resolvedor de URLs dentro de /api/, fora do DRF.
    return JsonResponse(envelope_erro(404), status=404)
