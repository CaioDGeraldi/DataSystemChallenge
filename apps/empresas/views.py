from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_GET

from apps.usuarios.services import validar_contexto_ativo


@login_required
@require_GET
def area(request):
    membro = validar_contexto_ativo(request, "gestao")
    return render(request, "datasystem/gestor/area.html", {"membro": membro})
