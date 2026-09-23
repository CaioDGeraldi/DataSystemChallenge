from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.empresas.services import lojas_autorizadas

from .exceptions import envelope_erro
from .serializers import ContextoSerializer, EnvelopeErroSerializer, HealthSerializer


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


@csrf_exempt
def nao_encontrado(request, caminho):
    # Também cobre falhas do resolvedor de URLs dentro de /api/, fora do DRF.
    return JsonResponse(envelope_erro(404), status=404)
