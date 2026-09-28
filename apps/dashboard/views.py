from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_GET

from apps.empresas.apresentacao import contexto_gestao
from .services import ler_dashboard, resolver_escopo_dashboard


@login_required
@require_GET
def dashboard(request):
    escopo = resolver_escopo_dashboard(request)
    return render(request, 'datasystem/gestor/dashboard.html', {
        **contexto_gestao(escopo.membro, 'dashboard'),
        'escopo': escopo, 'dashboard': ler_dashboard(escopo),
    })
