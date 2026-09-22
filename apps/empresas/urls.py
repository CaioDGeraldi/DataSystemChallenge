from django.urls import path

from . import views

app_name = "empresas"
urlpatterns = [
    path("gestao/membros/", views.membros, name="membros"),
    path("gestao/membros/convidar/", views.convidar_membro, name="convidar_membro"),
    path("gestao/convites/<int:convite_id>/revogar/", views.revogar_convite_view, name="revogar_convite"),
    path("convites/<str:token>/aceitar/", views.aceitar_convite_view, name="aceitar_convite"),
    path("onboarding/empresa/", views.onboarding, name="onboarding"),
    path("gestao/", views.area, name="area"),
    path("gestao/lojas/nova/", views.criar_loja, name="criar_loja"),
]
