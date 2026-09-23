from django.urls import path

from .views import ContextoView, HealthView


urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("contexto/", ContextoView.as_view(), name="contexto"),
]
