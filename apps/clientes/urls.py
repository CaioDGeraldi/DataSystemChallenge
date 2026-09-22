from django.urls import path

from . import views

app_name = "clientes"
urlpatterns = [
    path("empresa/<slug:slug>/cadastro/", views.cadastro, name="cadastro"),
    path("cliente/", views.area, name="area"),
]
