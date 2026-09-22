from django.urls import path

from . import views

app_name = "empresas"
urlpatterns = [
    path("onboarding/empresa/", views.onboarding, name="onboarding"),
    path("gestao/", views.area, name="area"),
    path("gestao/lojas/nova/", views.criar_loja, name="criar_loja"),
]
