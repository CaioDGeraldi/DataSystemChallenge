from django.urls import path

from . import views

app_name = "usuarios"
urlpatterns = [
    path("login/", views.login, name="login"),
    path("contextos/", views.selecionar_contexto, name="selecionar_contexto"),
    path("logout/", views.logout, name="logout"),
]
