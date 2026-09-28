from django.urls import path

from . import views

app_name = "clientes"
urlpatterns = [
    path("empresa/<slug:slug>/cadastro/", views.cadastro, name="cadastro"),
    path("cliente/pontos/", views.pontos, name="pontos"),
    path("cliente/resgates/", views.resgates, name="resgates"),
    path("cliente/programa/", views.trocar_programa, name="trocar_programa"),
    path("cliente/", views.area, name="area"),
]
