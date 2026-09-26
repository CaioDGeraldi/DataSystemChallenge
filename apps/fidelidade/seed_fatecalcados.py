"""Cenário de demonstração F4.01. Não contém regras gerais do programa.

Identidades e fatos narrativos são estáveis; PKs, segredos e datas técnicas não.
Nenhum histórico é removido, atualizado ou emitido fora dos services oficiais.
"""
import re
from calendar import monthrange
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Context, Decimal, localcontext
from hashlib import sha256
from threading import RLock, get_ident
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.db.models import Q
from django.db.models.signals import post_save
from django.http import HttpRequest

from apps.clientes.services import cadastrar_cliente
from apps.empresas.models import Empresa, Loja
from apps.empresas.services import (
    concluir_onboarding, criar_credencial, criar_loja_no_contexto,
    salvar_configuracao_empresa,
)
from apps.usuarios.services import resolver_identidade
from apps.usuarios.validators import validar_cpf
from apps.empresas.validators import validar_cnpj

from . import resgates
from .calculos import calcular_expiracao
from .consumo import alocacoes_com_consumo_efetivo
from .eventos import criar_evento
from .models import AlocacaoResgate, AplicacaoEfeitoEventoLote, Compra, LotePontos, Resgate
from .niveis import classificar_cliente, criar_nivel
from .services import registrar_compra


NOME_EMPRESA = 'FATECalçados'
SLUG = 'fatecalcados'
PREFIXO = 'FATE-DEMO-V1-'
FUSO = ZoneInfo('America/Sao_Paulo')
LOJAS = (
    ('Centro', 'Araras'), ('Jardim Aurora', 'Araras'), ('Estação', 'Araras'),
    ('Centro', 'Limeira'), ('Vila das Flores', 'Limeira'), ('Parque Sul', 'Limeira'),
    ('Centro', 'Rio Claro'), ('Jardim Horizonte', 'Rio Claro'), ('Terminal', 'Rio Claro'),
    ('Centro', 'Campinas'), ('Jardim Ipê', 'Campinas'), ('Parque das Águas', 'Campinas'),
)
POLITICA = dict(pontos_por_real=Decimal('1.00'), validade_pontos_meses=12,
    resgate_minimo_pontos=100, incremento_resgate_pontos=100,
    valor_monetario_por_ponto=Decimal('0.05'), precisao_pontos=2,
    modo_arredondamento_pontos='HALF_UP', periodo_cliente_ativo_dias=180)
RESGATES = (('A01', 2000), ('A02', 500), ('A03', 500), ('A04', 500),
            ('A05', 500), ('A06', 500), ('M01', 200), ('M02', 200))
PERSONAGENS = ('A01', 'B01', 'I01', 'M01', 'U01', 'M02')


def _cpf(indice):
    base = str(731820000 + indice)
    for tamanho in (9, 10):
        digito = sum(int(d) * (tamanho + 1 - i) for i, d in enumerate(base)) * 10 % 11
        base += str(0 if digito == 10 else digito)
    return base


def _cnpj():
    base = '731826490001'
    for pesos in ((5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2), (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)):
        resto = sum(int(d) * p for d, p in zip(base, pesos)) % 11
        base += str(0 if resto < 2 else 11 - resto)
    return base


CNPJ = _cnpj()
CPF_ADMIN = _cpf(0)


@dataclass(frozen=True)
class Pessoa:
    codigo: str
    nome: str
    cpf: str
    compras: int
    ticket: Decimal


def populacao():
    grupos = (
        ('A', ('Marina Valença', 'Davi Alvorada', 'Cecília Luar', 'Nilo Castanheira', 'Íris Venturo', 'Tomás Brisa')),
        ('M', ('Ravi Monteiro', 'Bento Amaral', 'Clara Vereda', 'Vítor Avelar', 'Mila Campestre',
               'Noel Figueira', 'Luna Paineira', 'Caetano Rios', 'Elisa Prado', 'Hugo Azular')),
        ('B', ('Otávio Cedro', 'Bianca Orvalho', 'Ítalo Serra', 'Nara Pontal', 'Lívio Marés',
               'Flora Cedrinho', 'Raul Violeta', 'Dora Nascente')),
        ('U', ('Lia Nogueira', 'Gael Jasmin', 'Cora Estrela', 'Ian Valejo', 'Sara Fontes', 'Teo Solar')),
        ('I', ('Helena Fontoura', 'Mauro Limoeiro', 'Rosa Horizonte', 'Enzo Salgueiro', 'Alma Pinhal', 'Léo Boreal')),
    )
    pessoas = []
    for grupo, nomes in grupos:
        for i, nome in enumerate(nomes):
            quantidade = {'A': 20, 'M': 10, 'B': 6, 'U': 1, 'I': 5 if i < 2 else 4}[grupo]
            ticket = {'A': Decimal(300 + 20 * i), 'M': Decimal(180 + 10 * i),
                      'B': Decimal(f'{69 + 10 * i}.90'), 'U': Decimal(f'{149 + 20 * i}.90'),
                      'I': Decimal(1100 if i == 0 else 250 + 25 * i)}[grupo]
            if grupo == 'M' and i < 2:
                ticket = Decimal('179.90') if i == 0 else Decimal('89.90')
            pessoas.append(Pessoa(f'{grupo}{i + 1:02}', nome, _cpf(len(pessoas) + 1), quantidade, ticket))
    return tuple(pessoas)


@dataclass(frozen=True)
class Venda:
    identificador: str
    cliente: str
    loja: int
    valor: Decimal
    ocorrida_em: datetime
    campanha: bool


@dataclass(frozen=True)
class Plano:
    referencia: datetime
    inicio_campanha: datetime
    fim_campanha: datetime
    vendas: tuple[Venda, ...]


def interpretar_data(texto):
    if not isinstance(texto, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', texto):
        raise CommandError('Use --data-base YYYY-MM-DD, sem horário ou espaços.')
    try:
        return date.fromisoformat(texto)
    except ValueError as exc:
        raise CommandError('Data-base inexistente no calendário.') from exc


def _mes(instante, deslocamento, dia=None):
    ano, mes = divmod(instante.year * 12 + instante.month - 1 + deslocamento, 12)
    mes += 1
    return instante.replace(year=ano, month=mes, day=min(dia or instante.day, monthrange(ano, mes)[1]))


def montar_plano(data_base):
    """Agenda pura: quotas por grupo e faixa mensal, sem acesso ao banco/relógio."""
    if type(data_base) is not date:
        raise CommandError('Informe uma data-base sem horário.')
    t = datetime.combine(data_base, time(12), FUSO)
    try:
        _mes(t, -15)
        _mes(t, 12).astimezone(ZoneInfo('UTC'))
    except (ValueError, OverflowError) as exc:
        raise CommandError('Data-base não comporta o histórico de 15 meses e a validade de 12 meses.') from exc
    inicio = (t - timedelta(days=45)).replace(hour=0)
    fim = (t - timedelta(days=38)).replace(hour=23, minute=59, second=59)
    pessoas = {p.codigo: p for p in populacao()}
    restantes = {p.codigo: p.compras for p in pessoas.values()}
    quotas = [60, 80, 80, 80]
    meses = Counter()
    vendas = []

    def adicionar(codigo, instante, campanha=False):
        offset = (instante.year - t.year) * 12 + instante.month - t.month
        faixa = (offset + 15) // 4
        if not -15 <= offset <= 0 or instante > t or restantes[codigo] <= 0 or quotas[faixa] <= 0:
            raise CommandError('Agenda do seed excedeu as quotas temporais/populacionais.')
        numero = len(vendas) + 1
        instante = instante + timedelta(seconds=numero)
        if (inicio <= instante <= fim) != campanha:
            raise CommandError('Agenda de Compra divergente da campanha.')
        valor = Decimal('300') if campanha and codigo in ('M01', 'M02') else pessoas[codigo].ticket
        vendas.append(Venda(f'{PREFIXO}C{numero:03}', codigo, (numero - 1) % 12, valor, instante, campanha))
        restantes[codigo] -= 1
        quotas[faixa] -= 1
        meses[offset] += 1

    def instante_mes(offset):
        # Evita aplicações incidentais; datas sempre anteriores aos Resgates em T.
        for dia in range(1, 29):
            instante = _mes(t, offset, dia).replace(hour=9)
            if instante <= t and not inicio <= instante <= fim:
                return instante
        raise CommandError('Não foi possível reservar um dia fora da campanha.')

    for codigo in pessoas:
        if not codigo.startswith('I'):
            adicionar(codigo, (t - timedelta(days=5)).replace(hour=10))
    alvos = [f'A{i:02}' for i in range(1, 7)] * 2 + [f'M{i:02}' for i in range(1, 11)] + ['B02', 'B03']
    for i, codigo in enumerate(alvos):
        adicionar(codigo, (inicio + timedelta(days=i % 8)).replace(hour=10), campanha=True)
    for codigo in pessoas:
        if codigo.startswith('I'):
            offsets = (-15, -13, -11, -9, -8) if restantes[codigo] == 5 else (-14, -12, -10, -8)
            for offset in offsets:
                adicionar(codigo, instante_mes(offset))
    # Compras válidas suficientes para os Resgates, independentemente dos fillers.
    for i in range(1, 7):
        for offset in (-11, -10, -9, -8, -7, -6):
            adicionar(f'A{i:02}', instante_mes(offset))
    for offset in (-10, -9):
        adicionar('M02', instante_mes(offset))
    adicionar('B01', (_mes(t, -12) + timedelta(days=7)).replace(hour=10))

    while any(restantes.values()):
        for codigo in pessoas:
            if restantes[codigo]:
                faixa = next(i for i, quantidade in enumerate(quotas) if quantidade)
                offsets = range(-15 + 4 * faixa, -11 + 4 * faixa)
                offset = min(offsets, key=lambda m: (meses[m], m))
                adicionar(codigo, instante_mes(offset))
    if quotas != [0, 0, 0, 0] or len(meses) != 16:
        raise CommandError('Agenda incompleta.')
    return Plano(t, inicio, fim, tuple(sorted(vendas, key=lambda v: (v.ocorrida_em, v.identificador))))


_lock_relogio = RLock()


class _TimezoneDoSeed:
    """Proxy apenas do binding de resgates, com fallback real em outros contextos."""
    def __init__(self, original):
        self.original = original
        self.instante = ContextVar('instante_seed_fatecalcados', default=None)

    def now(self):
        instante = self.instante.get()
        return instante if instante is not None else self.original.now()

    def __getattr__(self, nome):
        return getattr(self.original, nome)


@contextmanager
def _relogio_resgate(instante):
    # Não modifica django.utils.timezone.now nem models/defaults. Serializa apenas
    # instalações do proxy neste processo; outros contextos continuam no relógio real.
    with _lock_relogio:
        original = resgates.timezone
        proxy = _TimezoneDoSeed(original)
        token = proxy.instante.set(instante)
        resgates.timezone = proxy
        try:
            yield
        finally:
            proxy.instante.reset(token)
            resgates.timezone = original


def _prechecar():
    cpfs = [CPF_ADMIN, *(p.cpf for p in populacao())]
    if Empresa.objects.filter(Q(cnpj=CNPJ) | Q(slug=SLUG) | Q(nome__iexact=NOME_EMPRESA)).exists():
        raise CommandError('FATECalçados/CNPJ/slug reservado já existe. Use outro banco de demonstração limpo.')
    if get_user_model().objects.filter(cpf__in=cpfs).exists():
        raise CommandError('CPF reservado do cenário já existe. Nenhuma identidade será reutilizada.')
    if (Compra.objects.filter(identificador_externo__startswith=PREFIXO).exists()
            or Resgate.objects.filter(identificador_externo__startswith=PREFIXO).exists()):
        raise CommandError('Identificador de operação reservado já existe.')


def _exigir_identidade_nova(cpf, operacao):
    # O cadastro oficial pode autenticar um CPF surgido depois da pré-checagem.
    # Observar a criação evita reutilizá-lo mesmo nessa corrida; não substitui saves.
    criados = set()
    thread = get_ident()

    def observar(sender, instance, created, **kwargs):
        if created and instance.cpf == cpf and get_ident() == thread:
            criados.add(instance.pk)

    usuario_model = get_user_model()
    post_save.connect(observar, sender=usuario_model, weak=False)
    try:
        objeto = operacao()
        usuario_id = objeto.pk if isinstance(objeto, usuario_model) else objeto.usuario_id
        if usuario_id not in criados:
            raise CommandError('CPF reservado surgiu durante a carga; reutilização recusada e carga revertida.')
        return objeto
    finally:
        post_save.disconnect(observar, sender=usuario_model)


def _resumo_e_validacao(empresa, clientes, plano):
    compras = list(Compra.objects.filter(loja__empresa=empresa).select_related('lote_pontos', 'loja'))
    lotes = list(LotePontos.objects.filter(cliente__empresa=empresa))
    resgates_db = list(Resgate.objects.filter(loja__empresa=empresa))
    alocacoes = list(AlocacaoResgate.objects.filter(resgate__loja__empresa=empresa).select_related('lote'))
    aplicacoes = list(AplicacaoEfeitoEventoLote.objects.filter(lote__cliente__empresa=empresa))
    if (len(compras), len(lotes), len(resgates_db), len(aplicacoes)) != (300, 300, 8, 24):
        raise CommandError('Quantidades finais divergentes; carga revertida.')
    if (empresa.lojas.count(), empresa.clientes.count(), empresa.membros.count(),
            empresa.credenciais_integracao.count(), empresa.eventos_fidelidade.count()) != (12, 36, 1, 1, 1):
        raise CommandError('Estrutura final do tenant divergente.')
    if list(empresa.niveis_fidelidade.values_list('nome', 'pontos_minimos')) != [
            ('Bronze', Decimal('0')), ('Prata', Decimal('1000')), ('Ouro', Decimal('5000'))]:
        raise CommandError('Níveis finais divergentes.')
    esperadas = {v.identificador: v for v in plano.vendas}
    aplicados = {a.lote_id for a in aplicacoes}
    for compra in compras:
        venda = esperadas[compra.identificador_externo]
        lote = compra.lote_pontos
        if (compra.cliente_id != clientes[venda.cliente].pk
                or (compra.loja.nome, compra.loja.cidade) != LOJAS[venda.loja]
                or compra.valor != venda.valor or compra.ocorrida_em != venda.ocorrida_em
                or lote.expira_em != calcular_expiracao(compra.ocorrida_em, 12)
                or (lote.pk in aplicados) != venda.campanha
                or lote.pontos_concedidos != compra.valor * (2 if venda.campanha else 1)):
            raise CommandError('Concessão real divergente do cenário.')
    efetivas = set(alocacoes_com_consumo_efetivo(AlocacaoResgate.objects.filter(
        pk__in=[a.pk for a in alocacoes],
    )).values_list("pk", flat=True))
    consumido = Counter()
    por_resgate = Counter()
    for alocacao in alocacoes:
        if alocacao.pk in efetivas:
            consumido[alocacao.lote_id] += alocacao.pontos_consumidos
        por_resgate[alocacao.resgate_id] += alocacao.pontos_consumidos
    for resgate in resgates_db:
        if (por_resgate[resgate.pk] != resgate.pontos_resgatados
                or resgate.valor_desconto != resgate.pontos_resgatados * Decimal('0.05')):
            raise CommandError('Alocações incompletas.')
    if any(consumido[l.pk] > l.pontos_concedidos for l in lotes):
        raise CommandError('Consumo acima do concedido.')
    pessoas = []
    for p in populacao():
        cliente = clientes[p.codigo]
        classificacao = classificar_cliente(cliente)
        seus_lotes = [l for l in lotes if l.cliente_id == cliente.pk]
        saldo = sum((l.pontos_concedidos - consumido[l.pk] for l in seus_lotes
                     if l.expira_em > plano.referencia), Decimal('0.0000'))
        ultima = max(l.adquiridos_em for l in seus_lotes)
        recente = ultima > plano.referencia - timedelta(days=180)
        if recente == p.codigo.startswith('I'):
            raise CommandError('Disposição temporal de atividade divergente.')
        pessoas.append(dict(codigo=p.codigo, nome=p.nome, cpf=p.cpf, nivel=classificacao.nivel.nome,
            pontos=str(classificacao.pontos_para_nivel), saldo=str(saldo),
            ultima_compra=ultima.astimezone(FUSO).isoformat(), compra_na_janela_180d=recente))
    if not any(plano.referencia < l.expira_em <= plano.referencia + timedelta(days=14)
               for l in lotes if l.cliente_id == clientes['B01'].pk):
        raise CommandError('Ausente o caso de expiração próxima.')
    if not any(l.expira_em <= plano.referencia for l in lotes):
        raise CommandError('Ausente o histórico expirado.')
    if any(p['nivel'] != 'Ouro' for p in pessoas if p['codigo'] in ('A01', 'I01')):
        raise CommandError('Personagem sem classificação Ouro esperada.')
    bento = next(r for r in resgates_db if r.cliente_id == clientes['M02'].pk)
    if sum(a.resgate_id == bento.pk for a in alocacoes) < 2:
        raise CommandError('Resgate de Bento não atravessou Lotes.')
    return dict(data_base=plano.referencia.date().isoformat(), referencia=plano.referencia.isoformat(),
        empresa=NOME_EMPRESA, slug=empresa.slug, cpf_administrador=CPF_ADMIN,
        lojas=Loja.objects.filter(empresa=empresa).count(), clientes=len(clientes), compras=len(compras),
        lotes=len(lotes), aplicacoes_campanha=len(aplicacoes), resgates=len(resgates_db),
        alocacoes=len(alocacoes), pontos_resgatados=str(sum(r.pontos_resgatados for r in resgates_db)),
        descontos=str(sum(r.valor_desconto for r in resgates_db)),
        valor_compras=str(sum(c.valor for c in compras)),
        pontos_concedidos=str(sum(l.pontos_concedidos for l in lotes)),
        pontos_em_lotes_expirados=str(sum((l.pontos_concedidos for l in lotes
            if l.expira_em <= plano.referencia), Decimal('0.0000'))),
        saldo_em_t=str(sum(Decimal(p['saldo']) for p in pessoas)),
        distribuicao_niveis=dict(Counter(p['nivel'] for p in pessoas)), pessoas=pessoas)


def executar_seed(data_base, *, senha):
    plano = montar_plano(data_base)
    if connection.vendor != 'postgresql':
        raise CommandError('O seed exige PostgreSQL.')
    if not senha:
        raise CommandError('Defina RETORNA_SEED_SENHA para as contas fictícias; não use senha real.')
    validar_cnpj(CNPJ)
    for cpf in (CPF_ADMIN, *(p.cpf for p in populacao())):
        validar_cpf(cpf)
    _prechecar()
    with transaction.atomic(), localcontext(Context(prec=40)):
        # Arbitragem exclusiva do comando, antes de qualquer escrita. A segunda
        # execução espera o commit/rollback e repete todas as pré-checagens.
        chave = int.from_bytes(sha256(b'retorna:seed:fatecalcados:v1').digest()[:8], 'big', signed=True)
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', [chave])
        _prechecar()
        admin = _exigir_identidade_nova(CPF_ADMIN, lambda: resolver_identidade(cpf=CPF_ADMIN,
            senha=senha, confirmacao=senha, first_name='Administração', last_name='FATE Demonstração'))
        request = HttpRequest()
        request.user, request.session = admin, {}
        membro = concluir_onboarding(request, nome_empresa=NOME_EMPRESA, cnpj=CNPJ,
            nome_loja=LOJAS[0][0], cidade_loja=LOJAS[0][1])
        empresa = membro.empresa
        if empresa.slug != SLUG:
            raise CommandError('Colisão concorrente de slug; carga revertida.')
        lojas = [Loja.objects.get(empresa=empresa)]
        lojas.extend(criar_loja_no_contexto(request, nome=nome, cidade=cidade) for nome, cidade in LOJAS[1:])
        salvar_configuracao_empresa(request, **POLITICA)
        for nome, pontos in (('Bronze', '0'), ('Prata', '1000'), ('Ouro', '5000')):
            criar_nivel(request, nome=nome, pontos_minimos=Decimal(pontos))
        clientes = {}
        for p in populacao():
            nome, sobrenome = p.nome.split(' ', 1)
            clientes[p.codigo] = _exigir_identidade_nova(p.cpf, lambda: cadastrar_cliente(
                empresa=empresa, cpf=p.cpf, senha=senha, confirmacao=senha, first_name=nome, last_name=sobrenome))
        credencial, _ = criar_credencial(request, nome='FATE demonstração V1', escopo='EMPRESA')
        criar_evento(request, nome='Semana de passos em dobro', inicio_em=plano.inicio_campanha,
            fim_em=plano.fim_campanha, escopo='EMPRESA',
            efeitos=[{'tipo': 'MULTIPLICADOR_PONTOS', 'valor': Decimal('2.0000')}])
        for venda in plano.vendas:
            _, criada = registrar_compra(credencial=credencial, loja_id=lojas[venda.loja].pk,
                cliente_cpf=clientes[venda.cliente].usuario.cpf, identificador_externo=venda.identificador,
                valor=venda.valor, ocorrida_em=venda.ocorrida_em)
            if not criada:
                raise CommandError('Uma Compra reservada já existia; carga revertida.')
        for i, (codigo, pontos) in enumerate(RESGATES):
            with _relogio_resgate(plano.referencia - timedelta(minutes=8 - i)):
                _, criado = resgates.registrar_resgate(credencial=credencial, loja_id=lojas[i].pk,
                    cliente_cpf=clientes[codigo].usuario.cpf,
                    identificador_externo=f'{PREFIXO}R{i + 1:02}', pontos=pontos)
            if not criado:
                raise CommandError('Um Resgate reservado já existia; carga revertida.')
        return _resumo_e_validacao(empresa, clientes, plano)
