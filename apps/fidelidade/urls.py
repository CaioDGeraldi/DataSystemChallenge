from django.urls import path

from . import views

app_name = 'fidelidade'
urlpatterns = [
    path('gestao/niveis/', views.niveis, name='niveis'),
    path('gestao/niveis/novo/', views.novo_nivel, name='novo_nivel'),
    path('gestao/niveis/<int:nivel_id>/editar/', views.editar_nivel_view, name='editar_nivel'),
    path('gestao/niveis/<int:nivel_id>/excluir/', views.excluir_nivel_view, name='excluir_nivel'),
    path('gestao/eventos/', views.eventos, name='eventos'),
    path('gestao/eventos/novo/', views.novo_evento, name='novo_evento'),
    path('gestao/eventos/<int:evento_id>/cancelar/', views.cancelar_evento_view, name='cancelar_evento'),
]
