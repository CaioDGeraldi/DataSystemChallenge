from django.urls import path
from . import views

app_name = 'dashboard'
urlpatterns = [
    path('gestao/dashboard/', views.dashboard, name='inicio'),
    path('gestao/dashboard/vendas/', views.vendas, name='vendas'),
    path('gestao/dashboard/fidelidade/', views.fidelidade, name='fidelidade'),
    path('gestao/dashboard/clientes/', views.clientes, name='clientes'),
]
