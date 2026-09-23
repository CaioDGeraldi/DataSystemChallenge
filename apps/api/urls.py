from django.urls import include, path, re_path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from .views import nao_encontrado


app_name = "api"
urlpatterns = [
    path("v1/", include("apps.api.urls_v1")),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api:schema"), name="docs"),
    path("redoc/", SpectacularRedocView.as_view(url_name="api:schema"), name="redoc"),
    re_path(r"^(?P<caminho>.*)$", nao_encontrado),
]
