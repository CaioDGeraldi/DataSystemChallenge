# Roadmap do Produto

## Objetivo

Este roadmap organiza a evolução do DataSystemChallenge como plataforma de fidelidade independente, multiempresa, configurável e integrável por API.

A FATECalçados é apenas o cenário de demonstração da entrega. Nenhuma fase deve introduzir regras específicas da FATECalçados no domínio.

## Legenda

- ✅ concluído;
- 🟡 próximo/em andamento;
- ⏳ planejado;
- P0: obrigatório para a vertical principal da entrega;
- P1: importante se não comprometer P0;
- P2: melhoria posterior.

## Vertical principal da entrega

A prioridade é demonstrar um fluxo completo, não uma coleção de CRUDs independentes:

```text
Empresa
↓
1..N Lojas
↓
Configuração padrão da Empresa
↓
Override opcional da Loja
↓
Cliente
↓
Compra recebida pela API
↓
Motor de pontos
↓
Evento/Campanha temporária
↓
Dashboard
```

A API e sua documentação OpenAPI fazem parte da entrega, não são itens opcionais de pós-MVP.

## Fase 1 — Governança e base do repositório ✅

Objetivo: estabelecer processo de desenvolvimento verificável.

Entregue:

- Issues, branches, Pull Requests e Squash and merge;
- Conventional Commits;
- Kanban;
- templates de Issue/PR;
- workflow de validação;
- documentação de coordenação;
- registro do uso consciente de IA.

## Fase 2 — Fundação técnica e domínio

### F2.01 — Bootstrap Django e PostgreSQL ✅

Entregue:

- Django 5.2;
- PostgreSQL como banco de referência;
- `uv`;
- `CustomUser`;
- autenticação baseada em CPF;
- validação/normalização de CPF;
- estrutura inicial dos apps;
- testes e migrations iniciais.

### F2.02 — Empresa, Loja, Cliente e Gestor ✅

Entregue como primeira modelagem do domínio:

- `Empresa`;
- `Loja`;
- `Cliente`;
- `Gestor`;
- CNPJ validado/normalizado;
- relações protegidas com `PROTECT`;
- testes de domínio.

Essa modelagem foi válida para o estágio em que foi criada, mas `Cliente` e `Gestor` precisam evoluir para suportar o produto multiempresa consolidado posteriormente.

### Arquitetura multiempresa, parâmetros e API ✅

Consolidado em `docs/ARQUITETURA_PRODUTO.md` e `docs/API.md`:

- Empresa como tenant principal;
- `1..N` Lojas;
- parâmetros hierárquicos;
- overrides por Loja;
- eventos/campanhas;
- papel + escopo;
- API REST versionada;
- OpenAPI/Swagger/ReDoc;
- idempotência;
- isolamento multiempresa.

### F2.03A — Reconciliar domínio multiempresa 🟡 P0

Issue: #14.

Objetivo: remover as limitações estruturais da primeira modelagem antes de continuar cadastro e autorização.

Principais entregas:

- `Cliente` passa a representar `Usuario + Empresa`;
- um `Usuario` pode participar do programa de várias Empresas;
- criar `MembroEmpresa`;
- papéis iniciais `ADMINISTRADOR` e `GESTOR`;
- criar `AcessoLoja`;
- Gestor pode possuir `1..N` Lojas;
- Administrador possui acesso corporativo implícito;
- constraints de unicidade e isolamento entre Empresas;
- migrations incrementais;
- testes do novo domínio.

Esta fase bloqueia a continuação do fluxo antigo da Issue #11.

### F2.03B — Cadastro e autenticação por contexto ⏳ P0

A Issue #11 deverá ser revisada após a F2.03A.

Direção:

- cadastro de Cliente por Empresa;
- reutilização segura de `Usuario` existente em vez de duplicar identidade;
- login por CPF + senha;
- seleção de contexto;
- sessão com contexto ativo;
- autorização baseada no vínculo real com a Empresa;
- áreas mínimas protegidas.

### F2.04 — Onboarding de Empresa e membros ⏳ P0

Direção:

```text
Usuario
↓
cria Empresa
↓
se torna ADMINISTRADOR
↓
cria 1..N Lojas
↓
convida membros
↓
atribui papel
↓
se GESTOR, atribui 1..N Lojas
```

Inclui convite seguro, uso único, validade, revogação e reaproveitamento de identidade já existente.

### F2.05 — Parâmetros hierárquicos ⏳ P0

Objetivo: eliminar valores comerciais hardcoded antes do motor de fidelidade.

Direção:

```text
Padrão do produto
↓
Configuração da Empresa
↓
Override da Loja
```

Prioridades iniciais:

- pontos por real;
- validade dos pontos;
- resgate mínimo;
- incremento de resgate;
- conversão pontos/desconto;
- parâmetros necessários para cliente ativo e indicadores.

Lojas armazenam apenas overrides, não cópias dos padrões da Empresa.

### F2.06 — Base da API REST ⏳ P0

Objetivo: tornar integração uma capacidade nativa do produto.

Entregas mínimas:

- Django REST Framework;
- `/api/v1/`;
- health check;
- autenticação de integração;
- escopo Empresa/Loja;
- formato consistente de erros;
- OpenAPI;
- Swagger UI;
- ReDoc;
- documentação conceitual de integração;
- testes de isolamento cross-tenant.

## Fase 3 — Motor de fidelidade

### F3.01 — Compra e idempotência ⏳ P0

Primeiro recurso transacional central exposto para integração.

Direção:

- `Compra` pertence a uma Loja;
- identificador externo da venda;
- prevenção de duplicidade em retries;
- valor com `Decimal`;
- data/hora da venda;
- vínculo com Cliente da Empresa;
- endpoint `POST /api/v1/compras/`;
- consumidor envia fatos da venda, não pontos calculados.

A plataforma continua responsável pela fidelidade; não substitui o PDV.

### F3.02 — Motor de pontos e LotePontos ⏳ P0

Objetivo: calcular pontos a partir da configuração efetiva.

Fluxo:

```text
Compra
↓
resolver Empresa/Loja
↓
resolver parâmetros
↓
calcular pontos
↓
registrar resultado histórico
↓
criar LotePontos
```

Cada transação guarda o resultado aplicado para não ser recalculada quando configurações futuras mudarem.

### F3.03 — Eventos/Campanhas ⏳ P0

Primeira capacidade priorizada:

- nome;
- período;
- escopo Empresa ou conjunto de Lojas;
- multiplicador temporário de pontos.

Exemplo de demonstração:

```text
Loja herda 1 ponto/R$1
+ Black Friday 2x
+ Compra R$200
= 400 pontos
```

Para a entrega inicial, campanhas conflitantes sobre a mesma regra/Loja/período devem ser impedidas em vez de combinadas implicitamente.

### F3.04 — Resgate e consumo de lotes ⏳ P0/P1

Direção:

- `Resgate`;
- `AlocacaoResgate`;
- saldo suficiente;
- mínimo/incremento parametrizados;
- consumo dos lotes que expiram primeiro;
- valor financeiro do desconto registrado historicamente;
- endpoint de integração quando necessário.

Se o prazo apertar, o fluxo mínimo de resgate vem após Compra + pontos + evento.

### F3.05 — Níveis configuráveis ⏳ P1

Bronze/Prata/Ouro não são enums obrigatórios do produto.

Direção futura:

- níveis por Empresa;
- nome;
- ordem;
- faixa;
- benefício configurável dentro das capacidades suportadas.

A regra exata do benefício Prata/Ouro do cenário de demonstração continua dependendo de definição inequívoca do requisito.

## Fase 4 — Dados e visualização

### F4.01 — Seed determinístico e coerente ⏳ P0

Objetivo: alimentar a demonstração pela mesma lógica de domínio usada em produção.

Cenário FATECalçados:

- 12 Lojas como dados, não constante de código;
- pelo menos 20 Clientes;
- pelo menos 200 Compras;
- múltiplos níveis/faixas;
- clientes recorrentes e não recorrentes;
- resgates;
- pontos próximos de expirar;
- eventos/campanhas;
- distribuição temporal suficiente para gráficos.

Preferência: aproximadamente 36 Clientes e 300 Compras para tornar os indicadores mais convincentes, desde que o prazo comporte.

### F4.02 — Dashboard do Gestor ⏳ P0

Indicadores essenciais:

- clientes ativos;
- ticket médio;
- total/custo de descontos;
- ranking de pontos acumulados;
- evolução temporal;
- total de clientes;
- distribuição por níveis quando implementados;
- pontos acumulados x resgatados;
- taxa de recompra, se disponível de forma coerente.

Escopo:

- Administrador: Empresa inteira ou Loja selecionada;
- Gestor: somente Lojas autorizadas;
- filtros por período e Loja quando aplicável.

### F4.03 — Área do Cliente ⏳ P1

Direção:

- saldo;
- pontos próximos de expirar;
- nível/benefício quando implementado;
- histórico de compras/pontos;
- histórico de resgates.

Interface mobile-first e separada visualmente do painel administrativo.

## Fase 5 — Qualidade da entrega

### F5.01 — Acessibilidade e acabamento ⏳ P1

- responsividade;
- foco de teclado;
- labels;
- contraste;
- estados sem depender apenas de cor;
- modo claro/escuro quando viável;
- tamanho de texto e alto contraste como melhorias priorizadas se não comprometerem P0.

### F5.02 — Documentação final e API ⏳ P0

- OpenAPI compatível com endpoints reais;
- exemplos de request/response;
- autenticação;
- idempotência;
- erros;
- integração com PDV;
- limitações conhecidas;
- uso de IA atualizado.

### F5.03 — Pitch e validação final ⏳ P0

A demonstração deve contar uma história única:

```text
Criar/configurar Empresa
↓
Loja herda regra
↓
criar Evento 2x
↓
registrar Compra pela API
↓
pontos são calculados pelo domínio
↓
resultado aparece no Dashboard
```

A equipe deve conseguir explicar arquitetura, parâmetros, segurança, API, uso de IA, limitações e decisões de escopo.

## Priorização

### P0 — não sacrificar

- domínio multiempresa correto;
- Empresa + N Lojas;
- Cliente por Empresa;
- Administrador/Gestor + escopo;
- parâmetros Empresa → Loja;
- API versionada e documentada;
- Compra idempotente;
- motor de pontos;
- pelo menos um Evento/Campanha funcional;
- seed coerente;
- dashboard com os requisitos essenciais;
- testes dos fluxos críticos e isolamento entre Empresas.

### P1 — importante se P0 estiver seguro

- resgate completo se não couber dentro do P0 temporal;
- níveis totalmente configuráveis;
- taxa de recompra;
- área do Cliente mais completa;
- acessibilidade ampliada;
- auditoria inicial.

### P2 — depois da entrega

- OAuth2 completo;
- microserviços;
- múltiplos bancos por tenant;
- campanhas combináveis com prioridades complexas;
- motor genérico de regras;
- aplicativo mobile nativo;
- webhooks avançados;
- permissões administrativas muito granulares;
- observabilidade e auditoria avançadas.

## Regra de controle de escopo

Nova funcionalidade só entra no P0 se for necessária para completar a vertical principal ou atender requisito obrigatório da entrega.

Se uma ideia nova colocar em risco Empresa → Loja → Configuração → API → Compra → Pontos → Evento → Dashboard, ela deve ser classificada como P1 ou P2.