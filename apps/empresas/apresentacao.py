"""Contexto visual de Gestão. Não autoriza requests nem substitui os services."""
from django.urls import reverse

from .models import MembroEmpresa


def contexto_gestao(membro, secao, pagina=None):
    """Recebe exclusivamente o vínculo já validado pela view/service chamador."""
    entradas = [('lojas', 'Lojas', 'empresas:area')]
    if membro.papel == MembroEmpresa.Papel.ADMINISTRADOR:
        entradas = [
            ('lojas', 'Lojas', 'empresas:area'),
            ('membros', 'Membros', 'empresas:membros'),
            ('configuracao', 'Configuração', 'empresas:configuracao_empresa'),
            ('niveis', 'Níveis', 'fidelidade:niveis'),
            ('campanhas', 'Campanhas', 'fidelidade:eventos'),
            ('integracoes', 'Integrações', 'empresas:integracoes'),
        ]
    entradas.insert(0, ('dashboard', 'Dashboard', 'dashboard:inicio'))
    navegacao = [dict(chave=chave, nome=nome, url=reverse(rota), ativo=chave == secao)
                for chave, nome, rota in entradas]
    atual = next(item for item in navegacao if item['ativo'])
    breadcrumbs = [{'rotulo': atual['nome'], 'url': atual['url'] if pagina else None}]
    if pagina:
        breadcrumbs.append({'rotulo': pagina, 'url': None})
    return {
        'breadcrumbs': breadcrumbs,
        'back_url': atual['url'] if pagina else None,
        'back_label': f"Voltar para {atual['nome']}",
        'template_base': 'datasystem/gestao_base.html',
        'gestao': {
            'empresa': membro.empresa,
            'papel': membro.get_papel_display(),
            'secao': next((item['nome'] for item in navegacao if item['ativo']), 'Gestão'),
            'navegacao': navegacao,
        },
    }
