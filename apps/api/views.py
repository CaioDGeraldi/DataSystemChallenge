from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.empresas.services import lojas_autorizadas
from apps.fidelidade.services import registrar_compra

from .exceptions import envelope_erro
from .serializers import ContextoSerializer, EnvelopeErroSerializer, HealthSerializer
from .serializers import CompraSerializer, RegistrarCompraSerializer


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
class CompraView(APIView):
    http_method_names = ["post", "options"]

    @extend_schema(
        request=RegistrarCompraSerializer,
        responses={
            201: OpenApiResponse(CompraSerializer, description="Compra criada."),
            200: OpenApiResponse(CompraSerializer, description="Retry equivalente; Compra original preservada."),
            400: OpenApiResponse(EnvelopeErroSerializer, description="requisicao_invalida"),
            401: OpenApiResponse(EnvelopeErroSerializer, description="credencial_invalida"),
            403: OpenApiResponse(EnvelopeErroSerializer, description="loja_fora_do_escopo"),
            404: OpenApiResponse(EnvelopeErroSerializer, description="cliente_nao_encontrado"),
            409: OpenApiResponse(EnvelopeErroSerializer, description="idempotencia_conflitante"),
            405: OpenApiResponse(EnvelopeErroSerializer, description="metodo_nao_permitido"),
        },
        description="Registra fatos da venda, sem pontos. Idempotência por Loja + identificador externo.",
    )
    def post(self, request):
        entrada = RegistrarCompraSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        compra, criada = registrar_compra(credencial=request.auth, **entrada.validated_data)
        return Response(CompraSerializer(compra).data, status=201 if criada else 200)


@csrf_exempt
def nao_encontrado(request, caminho):
    # Também cobre falhas do resolvedor de URLs dentro de /api/, fora do DRF.
    return JsonResponse(envelope_erro(404), status=404)
