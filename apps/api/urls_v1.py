from django.urls import path

from .views import CompraView, ContextoView, HealthView, ResgateView


urlpatterns = [
    path('resgates/', ResgateView.as_view(), name='resgates'),
    path("compras/", CompraView.as_view(), name="compras"),
    path("health/", HealthView.as_view(), name="health"),
    path("contexto/", ContextoView.as_view(), name="contexto"),
]
