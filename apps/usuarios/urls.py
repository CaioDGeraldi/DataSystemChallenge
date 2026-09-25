from django.urls import path

from . import views

app_name = "usuarios"
urlpatterns = [
    path("para-empresas/", views.para_empresas, name="para_empresas"),
    path("", views.home, name="home"),
    path("login/", views.login, name="login"),
    path("contextos/", views.selecionar_contexto, name="selecionar_contexto"),
    path("logout/", views.logout, name="logout"),
]
