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
Níveis e Resgate
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

## Fase 2 — Fundação técnica e domínio ✅

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

Essa primeira modelagem foi posteriormente reconciliada pela F2.03A para suportar corretamente identidade global, múltiplas Empresas e escopo por Loja.

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

### F2.03A — Reconciliar domínio multiempresa ✅ P0

Issue: #14.

Entregue:

- `Usuario` permanece como identidade global;
- `Cliente` representa `Usuario + Empresa`;
- um `Usuario` pode participar do programa de várias Empresas;
- `MembroEmpresa` representa vínculo administrativo com a Empresa;
- papéis iniciais `ADMINISTRADOR` e `GESTOR`;
- `AcessoLoja` representa o escopo explícito de Gestor;
- Gestor pode possuir `1..N` Lojas;
- Administrador possui escopo corporativo implícito para Lojas atuais e futuras;
- papel e escopo permanecem conceitos separados;
- relações principais protegidas com `PROTECT`;
- invariantes multiempresa e constraints incrementais;
- testes do domínio no PostgreSQL.

Limitação aceita: operações como `QuerySet.update`, bulk e SQL bruto não são caminhos normais do domínio e podem contornar validações de model.

### F2.03B — Cadastro e autenticação por contexto ✅ P0

Issue: #11.

Entregue:

- cadastro público de Cliente por Empresa;
- reutilização segura de `Usuario` existente mediante prova de senha;
- login global por CPF + senha;
- contextos derivados dos vínculos reais de Cliente e `MembroEmpresa`;
- seleção explícita quando existem múltiplos contextos;
- sessão com somente `tipo_contexto`, `empresa_id` e `vinculo_id`;
- autorização revalidada no banco a cada acesso protegido;
- áreas mínimas de Cliente e Gestão;
- logout via POST + CSRF;
- `Empresa.slug` único e estável;
- testes de concorrência, autenticação, autorização e migration.

Limitação conhecida: diferenças de resposta no cadastro ainda podem permitir inferência da existência de um CPF; uniformização de mensagens e rate limiting ficam para endurecimento posterior.

### F2.04A — Onboarding de Empresa e primeira Loja ✅ P0

Issue: #21.

Entregue:

- onboarding público para identidade nova ou existente;
- criação atômica de `Empresa + primeira Loja + MembroEmpresa ADMINISTRADOR`;
- geração de slug único no backend;
- reaproveitamento da identidade global existente;
- ativação do novo contexto de Gestão após sucesso;
- criação de Lojas adicionais somente por Administrador ativo;
- Administrador vê todas as Lojas do tenant;
- Gestor vê somente Lojas de `AcessoLoja`;
- testes de atomicidade, concorrência, autorização e tenancy.

### F2.04B — Convites de membros e atribuição de Lojas ✅ P0

Issue: #23.

Entregue:

- convites direcionados por CPF;
- token criptograficamente aleatório com somente hash persistido;
- validade de 7 dias;
- uso único e revogação explícita;
- convite para `ADMINISTRADOR` ou `GESTOR`;
- `GESTOR` exige `1..N` Lojas explícitas do próprio tenant;
- aceite atômico com reutilização ou criação de `Usuario`;
- criação de `MembroEmpresa` e `AcessoLoja` somente no aceite;
- proteção contra aceite duplicado e concorrência;
- telas mínimas de membros e convites;
- testes de rollback, identidade, sessão, tenancy e permissões.

### F2.05 — Parâmetros hierárquicos ✅ P0

Issue: #25.

Entregue:

```text
Padrão do produto
↓
Configuração da Empresa
↓
Override opcional da Loja
```

- defaults tipados e centralizados;
- `ConfiguracaoFidelidadeEmpresa` com parâmetros P0;
- `OverrideFidelidadeLoja` somente para `pontos_por_real` nesta fase;
- `Decimal` para pontuação fracionária e valores monetários;
- ausência de override significa herança dinâmica da Empresa;
- `0.00` é um override válido e não é confundido com ausência;
- serviço somente leitura para resolver configuração efetiva;
- isolamento cross-tenant no backend;
- edição restrita a Administrador ativo;
- migration incremental e testes de domínio, autorização, resolução e tenancy.

Níveis, benefícios, Compra, Resgate e eventos/campanhas permanecem fora desta fase.

### F2.06 — Base da API REST ✅ P0

Issue: #28.

Entregue:

- Django REST Framework e `drf-spectacular`;
- API versionada em `/api/v1/`;
- `GET /api/v1/health/` público;
- `GET /api/v1/contexto/` autenticado;
- credenciais próprias de integração, separadas de `Usuario`;
- autenticação por `X-API-Key: <identificador>.<segredo>`;
- segredo bruto exibido somente na criação e persistência apenas do hash;
- escopos `EMPRESA` e `LOJAS`;
- imutabilidade da Empresa, do tipo de escopo e do conjunto emitido de Lojas pelos caminhos normais do domínio;
- helpers reutilizáveis de autorização por Loja;
- provisionamento e desativação de credenciais por Administrador ativo;
- envelope consistente para erros tratados;
- `/api/schema/`, `/api/docs/` e `/api/redoc/`;
- OpenAPI refletindo somente endpoints realmente implementados;
- testes de autenticação, tenancy, HTTP, CSRF, migration e schema.

Compra, idempotência transacional, pontos, Resgate, Cliente REST, níveis e campanhas/eventos permanecem futuros.

## Fase 3 — Motor de fidelidade

### F3.01 — Compra e idempotência 🟡 P0

Próxima fase da vertical principal.

Objetivo: implementar o primeiro recurso transacional central exposto para integração, sem antecipar ainda o cálculo de pontos da F3.02.

Direção:

- `Compra` pertence a uma Loja;
- identificador externo da venda;
- prevenção de duplicidade em retries;
- valor com `Decimal`;
- data/hora da venda;
- vínculo com Cliente da mesma Empresa da Loja;
- endpoint `POST /api/v1/compras/`;
- reutilização da autenticação e do escopo de integração entregues na F2.06;
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

Issue aberta: #26.

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

A implementação deve ocorrer após existir a base operacional de Compra e cálculo de pontos necessária para tornar o efeito demonstrável na vertical principal.

### F3.04 — Resgate e consumo de lotes ⏳ P0

O fluxo mínimo de resgate é obrigatório porque os indicadores exigem pontos resgatados, descontos e custo do programa.

Direção:

- `Resgate`;
- `AlocacaoResgate`;
- saldo suficiente;
- mínimo/incremento parametrizados;
- consumo dos lotes que expiram primeiro;
- valor financeiro do desconto registrado historicamente;
- endpoint de integração quando necessário.

Recursos sofisticados de resgate podem ficar em P1, mas o domínio necessário para demonstrar resgates reais precisa existir no P0.

### F3.05 — Níveis configuráveis ⏳ P0

A distribuição Bronze/Prata/Ouro faz parte dos indicadores esperados do cenário de demonstração, mas esses nomes não são enums obrigatórios do produto.

Direção mínima P0:

- níveis por Empresa;
- nome;
- ordem;
- faixa de pontos;
- classificação do Cliente a partir da configuração.

Benefícios avançados e composição flexível podem ficar em P1. A regra exata do benefício Prata/Ouro do cenário de demonstração continua dependendo de definição inequívoca do requisito antes de ser codificada.

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
- distribuição por níveis;
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
Cliente é classificado e pode resgatar
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
- níveis configuráveis mínimos para o cenário;
- resgate mínimo funcional;
- seed coerente;
- dashboard com os requisitos essenciais;
- testes dos fluxos críticos e isolamento entre Empresas.

### P1 — importante se P0 estiver seguro

- benefícios avançados dos níveis;
- variações sofisticadas de resgate;
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

Se uma ideia nova colocar em risco Empresa → Loja → Configuração → API → Compra → Pontos → Evento → Níveis/Resgate → Dashboard, ela deve ser classificada como P1 ou P2.
