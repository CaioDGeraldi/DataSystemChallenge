from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("api/", include("apps.api.urls")),
    path("admin/", admin.site.urls),
    path("", include("apps.usuarios.urls")),
    path("", include("apps.clientes.urls")),
    path("", include("apps.empresas.urls")),
    path("", include("apps.dashboard.urls")),
    path("", include("apps.fidelidade.urls")),
]
