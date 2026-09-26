from django.urls import path

from .views import (
    CompraView,
    ConsultaFidelidadeView,
    ContextoView,
    HealthView,
    ResgateView,
    EstornoResgateView,
    SimulacaoResgateView,
    SimulacaoCompraView,
)


urlpatterns = [
    path("resgates/estornar/", EstornoResgateView.as_view(), name="estornar-resgate"),
    path("clientes/fidelidade/", ConsultaFidelidadeView.as_view(), name="cliente-fidelidade"),
    path('resgates/simular/', SimulacaoResgateView.as_view(), name='simular-resgate'),
    path('resgates/', ResgateView.as_view(), name='resgates'),
    path("compras/simular/", SimulacaoCompraView.as_view(), name="simular-compra"),
    path("compras/", CompraView.as_view(), name="compras"),
    path("health/", HealthView.as_view(), name="health"),
    path("contexto/", ContextoView.as_view(), name="contexto"),
]
