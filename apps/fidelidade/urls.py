from django.urls import path

from . import views

app_name = 'fidelidade'
urlpatterns = [
    path('gestao/eventos/', views.eventos, name='eventos'),
    path('gestao/eventos/novo/', views.novo_evento, name='novo_evento'),
    path('gestao/eventos/<int:evento_id>/cancelar/', views.cancelar_evento_view, name='cancelar_evento'),
]
