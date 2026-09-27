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
Resgate
↓
Níveis
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

Compra e idempotência transacional foram entregues posteriormente na F3.01. O motor base de pontos e `LotePontos` foi entregue na F3.02. Campanhas/eventos temporários foram entregues na F3.03. Resgate idempotente e consumo histórico de Lotes foram entregues na F3.04. Níveis configuráveis foram entregues na F3.05. A consulta REST de fidelidade do Cliente foi entregue na F3.06B.

## Fase 3 — Motor de fidelidade

### F3.01 — Compra e idempotência ✅ P0

Issue: #34.

Entregue:

- `Compra` persistida em `apps.fidelidade` como fato histórico de venda;
- relações com Loja, Cliente e credencial de origem protegidas por `PROTECT`;
- coerência obrigatória de tenant entre Compra, Loja, Cliente e credencial;
- fatos materiais da Compra imutáveis após criação pelos caminhos normais do domínio;
- `identificador_externo` normalizado com limite de 255 caracteres;
- valor monetário com `DecimalField(max_digits=12, decimal_places=2)`, mínimo `0.01` e constraint positiva;
- data/hora da venda timezone-aware separada de `criada_em`;
- chave idempotente `Loja + identificador_externo` protegida por `UniqueConstraint`;
- `POST /api/v1/compras/` autenticado por `X-API-Key`;
- primeira criação retorna `201`, retry equivalente retorna `200` e conflito de fatos retorna `409 idempotencia_conflitante`;
- retry por outra credencial autorizada preserva `credencial_origem` e o restante do histórico original;
- concorrência resolvida por transação, savepoint e constraint PostgreSQL, sem converter outras falhas de integridade em retry;
- erros específicos de Loja fora do escopo e Cliente inexistente no tenant;
- OpenAPI e `docs/API.md` atualizados para o contrato real;
- migration inicial de `apps.fidelidade`;
- testes de domínio, HTTP, tenancy, idempotência, concorrência, migration e schema.

A F3.01 registra somente os fatos da venda. Pontos e `LotePontos` não são calculados nesta fase.

### F3.02 — Motor de pontos e LotePontos ✅ P0

Issue: #40.

Entregue:

- política corporativa de concessão com `precisao_pontos` em `0`, `1`, `2` ou `4` e `modo_arredondamento_pontos` em `HALF_UP`, `DOWN` ou `UP`;
- defaults do produto em 2 casas e `HALF_UP`;
- precisão física dos pontos fixa em quatro casas decimais;
- `pontos_por_real` continua podendo receber override por Loja, enquanto precisão e arredondamento permanecem corporativos;
- cálculo determinístico com `Decimal`, sem `float` ou `round()` binário;
- `LotePontos` 1:1 com `Compra`, Cliente obrigatório e relações históricas protegidas com `PROTECT`;
- snapshots da taxa, precisão, modo de arredondamento, validade, resultados e datas realmente aplicados;
- fatos de `LotePontos` imutáveis após criação pelos caminhos normais do domínio;
- taxa `0.00` continua criando Lote histórico com zero pontos;
- `adquiridos_em` usa `Compra.ocorrida_em` e a expiração usa meses de calendário em `America/Sao_Paulo`, com ajuste para o último dia válido do mês;
- expiração fora do intervalo representável é rejeitada como `400 requisicao_invalida`, sem truncamento, com rollback integral;
- novas Compras e seus Lotes são criados na mesma transação;
- retry equivalente retorna a mesma Compra e o mesmo Lote, sem recálculo, inclusive após mudança de configuração;
- concorrência continua arbitrada pela constraint da Compra e resulta em no máximo um Lote para a vencedora;
- Compras anteriores à F3.02 não recebem backfill; retry legado retorna `fidelidade: null`;
- `POST /api/v1/compras/` passou a retornar `pontos_base`, `pontos_concedidos` e `expira_em` no bloco `fidelidade`;
- migrations incrementais `empresas.0009` e `fidelidade.0002`;
- OpenAPI, `docs/API.md` e `docs/APRESENTACAO.md` atualizados;
- validação em PostgreSQL com 87 testes focais e 291 testes totais, além dos gates de migrations, diff, lock e OpenAPI.

Limitações deliberadas da F3.02: não havia backfill automático, saldo consumível, Resgate, campanhas/eventos, níveis ou versionamento temporal completo de configurações. Campanhas/eventos foram entregues posteriormente na F3.03, Resgate/saldo consumível na F3.04 e níveis configuráveis na F3.05. Operações bulk, `QuerySet.update` e SQL bruto continuam fora dos caminhos normais protegidos pelo model.

### F3.03 — Eventos/Campanhas ✅ P0

Issue: #26.

Entregue:

- `EventoFidelidade` separado de `EfeitoEvento`;
- escopo `EMPRESA`, cobrindo Lojas atuais e futuras do tenant, ou `LOJAS`, com conjunto relacional explícito;
- único efeito operacional nesta fase: `MULTIPLICADOR_PONTOS` com `DecimalField(max_digits=12, decimal_places=4)` e valor estritamente positivo;
- aplicabilidade temporal baseada em `Compra.ocorrida_em`, com limites inclusivos;
- cálculo `Compra.valor × pontos_por_real = pontos_base`, aplicação do multiplicador sobre a base exata e política corporativa de precisão/arredondamento aplicada uma única vez ao resultado final;
- `pontos_base` preservado como valor pré-campanha;
- `multiplicador_pontos_aplicado` imutável em `LotePontos`, com `1.0000` como snapshot neutro para operações sem campanha e Lotes históricos;
- `AplicacaoEfeitoEventoLote` para preservar proveniência histórica de Lote, Evento, Efeito, tipo e valor aplicados;
- campanha `1.0000x` também registra aplicação histórica quando efetivamente selecionada;
- definição de Evento, efeitos e conjunto de Lojas congelada após criação; mudança exige cancelar e criar novo Evento;
- cancelamento explícito `null → timestamp`, sem reativação, reescrita ou exclusão normal do histórico;
- estados `AGENDADO`, `VIGENTE`, `ENCERRADO` e `CANCELADO` derivados, sem campo redundante;
- conflitos do mesmo efeito bloqueados quando há período inclusivamente sobreposto e Loja efetivamente compartilhada, cobrindo `EMPRESA × EMPRESA`, `EMPRESA × LOJAS` e `LOJAS × LOJAS`;
- criação, cancelamento e resolução de campanha serializados por lock PostgreSQL da Empresa para evitar disputa concorrente de definição/aplicação;
- autorização de gestão restrita a Administrador ativo; Gestor não cria nem cancela Evento nesta fase;
- interface mínima para listar, criar e cancelar Eventos, sem CRUD público de campanhas na API;
- integração atômica `Compra + LotePontos + AplicacaoEfeitoEventoLote` para novas Compras vencedoras;
- retry equivalente preserva o histórico original sem resolver Evento novamente; Compras legadas sem Lote continuam retornando `fidelidade: null`;
- API pública de Compra preservada com `pontos_base`, `pontos_concedidos` e `expira_em`, sem expor snapshots internos da campanha;
- migration incremental `fidelidade.0003_eventos_fidelidade`;
- `docs/API.md` e `docs/APRESENTACAO.md` atualizados para o fluxo real;
- validação em PostgreSQL com 99 testes focais e 325 testes totais, além de `check`, `makemigrations --check`, migration aplicada, OpenAPI, `git diff --check` e `uv lock --check`.

Limitações deliberadas: somente `MULTIPLICADOR_PONTOS` é operacional; não há `BONUS_PONTOS_PERCENTUAL`, `DESCONTO_GERAL_PERCENTUAL`, backfill de campanhas, combinação automática de campanhas conflitantes nem versionamento temporal completo das configurações permanentes. Na F3.03 ainda não havia saldo consumível, Resgate ou níveis; Resgate foi entregue na F3.04 e níveis configuráveis na F3.05. Operações bulk, `QuerySet.update` e SQL bruto continuam fora dos caminhos normais protegidos pelo domínio.

### F3.04 — Resgate e consumo de lotes ✅ P0

Issue: #49.

Entregue:

- `Resgate` como fato histórico da operação e `AlocacaoResgate` como consumo histórico dos Lotes;
- saldo disponível derivado dos `pontos_concedidos` de Lotes ainda válidos menos alocações anteriores, sem campo de saldo materializado;
- pedido de Resgate com quantidade inteira positiva, persistida em `DecimalField(max_digits=20, decimal_places=0)`, enquanto alocações preservam quatro casas em `DecimalField(max_digits=24, decimal_places=4)`;
- consumo determinístico por FEFO: `expira_em ASC → adquiridos_em ASC → pk ASC`;
- instante do Resgate definido no servidor por `timezone.now()`, sem backdating; em `expira_em == resgatado_em` o Lote já está expirado;
- mínimo, incremento e valor monetário por ponto resolvidos na nova operação e preservados em snapshots históricos;
- desconto histórico em `DecimalField(max_digits=32, decimal_places=2)`, calculado com `Decimal` e `ROUND_HALF_UP`, sem `float` ou truncamento;
- `POST /api/v1/resgates/` autenticado por `X-API-Key`, com primeira criação `201`, retry equivalente `200` e conflito material `409 idempotencia_conflitante`;
- chave idempotente `Loja + identificador_externo`, protegida por `UniqueConstraint` e arbitrada antes do consumo com `pg_advisory_xact_lock` derivado deterministicamente de SHA-256;
- ordem de locks `advisory → Cliente → Lotes FEFO`, impedindo double-spend entre Resgates concorrentes com chaves diferentes para o mesmo Cliente;
- retry equivalente preservando credencial de origem, snapshots, desconto, instante e alocações, sem reler configuração, saldo ou expiração;
- relações históricas com `PROTECT`, imutabilidade de Resgate/alocações e bloqueio dos caminhos públicos de `update`, `bulk_update` e `bulk_create`;
- criação atômica de Resgate e todas as alocações, com rollback integral em falhas de validação, cálculo, persistência ou conjunto incompleto;
- consumo baseado em `LotePontos.pontos_concedidos`, incorporando campanhas já aplicadas sem recalcular Evento;
- migration incremental `fidelidade.0004_resgate_alocacaoresgate`;
- OpenAPI, `docs/API.md` e `docs/APRESENTACAO.md` atualizados para o contrato real;
- validação em PostgreSQL com 150 testes focais e 377 testes totais, além de `check`, `makemigrations --check`, migration aplicada, OpenAPI, `git diff --check` e `uv lock --check`.

Na F3.04 ainda não havia estorno, endpoint de consulta de fidelidade ou simulações públicas. A consulta foi entregue na F3.06B, as simulações na F3.06C/F3.06D e o estorno integral na F3.06E. Permanecem fora do contrato edição/backdating de Resgate, vínculo obrigatório Resgate → Compra e ledger genérico. APIs internas do ORM e SQL bruto continuam fora do contrato normal de escrita.

### F3.05 — Níveis configuráveis ✅ P0

Issue: #53. PR: #55.

Entregue:

- `NivelFidelidade` configurável por Empresa, sem hardcode de Bronze/Prata/Ouro;
- nome textual livre e `pontos_minimos` em `DecimalField(max_digits=24, decimal_places=4)`;
- threshold único por Empresa, não negativo e usado como ordenação da faixa;
- configuração vazia válida; quando existem níveis, o menor threshold deve ser exatamente `0.0000`;
- classificação derivada por `SUM(LotePontos.pontos_concedidos)` histórico;
- Lotes expirados continuam contando para nível;
- Resgates e `AlocacaoResgate` não reduzem o nível;
- inatividade não reduz o nível e continua sendo dimensão separada;
- campanhas contam por meio dos `pontos_concedidos` já persistidos, sem recálculo;
- nível não é materializado no `Cliente`, e não existe campo redundante de pontos acumulados;
- mudança dos thresholds pode reclassificar o estado atual sem reescrever o histórico de pontos;
- escrita de configuração restrita aos services transacionais;
- serialização por Empresa com `FOR NO KEY UPDATE`, seguindo a ordem Empresa → Administrador;
- gestão web mínima para listar, criar, editar e excluir níveis somente por Administrador ativo;
- isolamento cross-tenant, CSRF e exclusão somente por POST;
- sem API REST pública de níveis nesta fase;
- migration incremental `fidelidade.0005_nivelfidelidade`;
- `docs/ARQUITETURA_PRODUTO.md` e `docs/APRESENTACAO.md` atualizados;
- validação local com 32 testes focais e 409 testes totais, além de `check`, `makemigrations --check --dry-run`, migration aplicada, OpenAPI, `git diff --check` e `uv lock --check`.

Na F3.05, benefícios automáticos por nível permaneceram fora do escopo: a fase não associava Prata/Ouro a desconto, bônus, multiplicador ou conversão especial. Benefícios configuráveis por nível, suspensão opcional por inatividade e promoção de retorno foram entregues posteriormente na F3.06A. A consulta pública do estado de fidelidade do Cliente foi entregue na F3.06B. Permanecem futuros histórico explícito de mudanças de nível e área do Cliente enriquecida.

### F3.06A — Benefícios por nível, inatividade e promoção de retorno ✅ P0

Issue: #66. PR: #76.

Entregue:

- `NivelFidelidade` com `bonus_pontos_percentual` e `desconto_percentual` independentes, sem regras hardcoded para Bronze/Prata/Ouro;
- atividade baseada na última Compra anterior à operação e em `periodo_cliente_ativo_dias`, sem rebaixar o nível histórico;
- suspensão opcional de benefícios de nível por inatividade;
- primeira Compra tratada separadamente de retorno após inatividade: `ativo_antes=False`, `retorno=False`, sem promoção de retorno e com benefícios do nível inicial preservados;
- política configurável para a primeira Compra de retorno com `SEM_BENEFICIOS_NIVEL` ou `COM_BENEFICIOS_NIVEL`;
- promoção de retorno opcional, com bônus de pontos e desconto percentual independentes;
- combinação de descontos `ADITIVO` ou `SEQUENCIAL`, com valor final nunca negativo;
- ordem configurável do desconto monetário de Resgate antes ou depois dos descontos percentuais;
- base de cálculo de pontos `BRUTO` ou `LIQUIDO`;
- desconto monetário de nível sempre baseado no nível histórico anterior à Compra;
- `ANTES_DA_COMPRA` ou `ATINGIDO_NA_COMPRA` controlando somente o nível que fornece bônus de pontos;
- classificação provisória em passagem única usando progresso histórico + efeito da campanha, sem reclassificação causada pelo próprio bônus de nível ou pelo bônus de retorno;
- campanha, nível e retorno combinados de forma aditiva sobre os mesmos pontos base;
- avaliação central reutilizável em `apps/fidelidade/beneficios.py`, com `Decimal` e contexto próprio;
- snapshot versionado em `LotePontos.beneficios_aplicados`, preservando lotes legados com `NULL`, sem backfill ou recálculo;
- retry idempotente preservando o snapshot original sem reavaliar benefícios;
- serialização conservadora do fluxo real por lock `Empresa → Cliente`, evitando duas promoções simultâneas para o mesmo retorno;
- migrations incrementais `empresas.0010_beneficios_fidelidade` e `fidelidade.0006_beneficios_fidelidade`;
- `docs/ARQUITETURA_PRODUTO.md` atualizado para o contrato efetivamente implementado;
- validação final com 75 testes focais e 475 testes totais aprovados, além de `check`, `makemigrations --check --dry-run`, `git diff --check` e `uv lock --check`.

Os endpoints de consulta e simulação previstos após a F3.06A foram entregues nas F3.06B–F3.06D, o estorno integral de Resgate foi entregue na F3.06E e o contrato efetivo da Compra com benefícios e Resgate foi reconciliado na F3.06F.

### F3.06B — Consulta de fidelidade do Cliente ✅ P0

Issue: #67. PR: #81.

Entregue:

- `GET /api/v1/clientes/fidelidade/` autenticado por `X-API-Key`;
- consulta por `loja_id` e `cliente_cpf`, respeitando tenant e escopos `EMPRESA`/`LOJAS`;
- instante atual definido pelo servidor, sem aceitar backdating;
- reutilização do avaliador canônico da F3.06A para atividade, retorno e aplicabilidade de benefícios;
- separação entre progresso histórico usado para nível e saldo atualmente utilizável;
- exposição do nível atual, benefícios aplicáveis, promoção de retorno e parâmetros de Resgate;
- saldo derivado somente de Lotes ainda válidos e consumo efetivo;
- operação somente leitura, sem snapshots ou mutação de domínio;
- `Cache-Control: no-store`, OpenAPI e `docs/API.md` atualizados;
- validação com 6 testes específicos e 90 testes de regressão focada, além de `check`, OpenAPI, migrations sem mudanças e `git diff --check`.

### F3.06C — Simulação de Compra ✅ P0

Issue: #68. PR: #82.

Entregue:

- `POST /api/v1/compras/simular/` autenticado por `X-API-Key`;
- payload reduzido a Loja, Cliente e valor, rejeitando identificador externo, backdating e campos calculados pelo consumidor;
- instante atual definido pelo servidor;
- reutilização da avaliação canônica de fidelidade da F3.06A;
- consulta do Evento/Campanha aplicável sem persistência nem bloqueio de escrita;
- distinção entre nível histórico atual e nível usado exclusivamente para bônus quando `ATINGIDO_NA_COMPRA` está configurado;
- exposição dos descontos, componentes de pontos, atividade, retorno, campanha e promoção aplicáveis;
- ausência de persistência, idempotência ou efeitos colaterais na simulação;
- equivalência de regras com a Compra efetiva sem enfraquecer o fluxo transacional real;
- OpenAPI e `docs/API.md` atualizados;
- validação com 125 testes focados, além de `check`, OpenAPI, migrations sem mudanças e `git diff --check`.

### F3.06D — Simulação de Resgate ✅ P0

Issue: #69. PR: #83.

Entregue:

- `POST /api/v1/resgates/simular/` autenticado por `X-API-Key`;
- quantidade de pontos inteira, positiva e limitada pelo mesmo contrato do Resgate real;
- cálculo de saldo, mínimo, incremento e desconto reutilizando as mesmas regras materiais do Resgate efetivo;
- saldo projetado após o Resgate sem reservar ou persistir pontos;
- seleção dos Lotes ainda válidos sem `select_for_update`, advisory lock ou alteração de histórico;
- isolamento de tenant/Loja e ocultação de existência coerentes com o Resgate real;
- payload estrito, sem backdating, identificador externo ou campos derivados;
- OpenAPI e `docs/API.md` atualizados;
- validação final com 66 testes focados após as correções, além de `check`, OpenAPI, migrations sem mudanças e `git diff --check`.

### F3.06E — Estorno histórico e idempotente de Resgate ✅ P0

Issue: #70. PR: #84.

Entregue:

- `POST /api/v1/resgates/estornar/` para estorno sempre integral;
- `EstornoResgate` como fato histórico imutável, com no máximo um estorno por Resgate e chave idempotente própria por Loja;
- parâmetro corporativo `devolver_pontos_ao_estornar_resgate`, com default `true` e sem override por Loja nesta fase;
- snapshot `devolve_pontos_aplicado`, impedindo que mudanças futuras de configuração alterem estornos passados;
- regra fixa de domínio: pontos já expirados nunca voltam, a validade nunca é renovada e nenhum Lote substituto é criado;
- quando o snapshot é `true`, apenas alocações de Lotes ainda válidos deixam de representar consumo efetivo; com `false`, o consumo original permanece;
- consumo efetivo centralizado e reutilizado pela consulta, simulação, Resgate real e validação de capacidade das alocações;
- retry equivalente `200`, criação `201`, conflitos explícitos para chave reutilizada ou Resgate já estornado;
- serialização por advisory lock próprio e pelo mesmo lock de Cliente usado no Resgate real, preservando resultados serializáveis em concorrência;
- migrations `empresas.0011_configuracaofidelidadeempresa_devolver_pontos_ao_estornar_resgate` e `fidelidade.0007_estornoresgate`;
- OpenAPI, `docs/API.md` e `docs/MODELAGEM_DE_DADOS.md` atualizados;
- validação com 194 testes focados e 58 testes complementares aprovados, incluindo concorrência em PostgreSQL, além de `check`, OpenAPI, migrations sem mudanças e `git diff --check`.

### F3.06F — Reconciliar contrato efetivo da Compra com benefícios e Resgate ✅ P0

Issue: #71. PR: #86.

Entregue:

- `Compra` permanece como fonte histórica da venda e aceita associação opcional a um `Resgate` já efetivado por `resgate_identificador_externo`;
- relação histórica opcional 1:1 entre `Compra` e `Resgate`, com validação de tenant, Loja, Cliente, autorização e vínculo único;
- Resgate vinculado a Compra concluída não pode ser estornado isoladamente e retorna `409 resgate_vinculado_compra`;
- payload real de Compra rejeita campos extras e decisões derivadas enviadas pelo PDV;
- novo parâmetro corporativo `limite_resgate_percentual`, sem override por Loja, com FATECalçados configurada em 50%;
- máximo aplicável de Resgate considera saldo, mínimo, incremento, conversão, teto percentual sobre o bruto e capacidade efetiva conforme a ordem de aplicação;
- a parcela paga por Resgate nunca gera novos pontos: em `BRUTO`, a base elegível exclui o desconto de Resgate; em `LIQUIDO`, usa o valor final após Resgate e descontos percentuais;
- snapshot de benefícios evoluído para v2, preservando compatibilidade de reavaliação com snapshots v1;
- consulta e simulação expõem disponibilidade e máximo de Resgate sem persistir ou reservar saldo;
- resposta da Compra acrescenta Resgate e resumo histórico explicável sem expor snapshots internos;
- Gestão recebeu prévia e tabela de conversão de Resgate com 10 linhas por página, baseada nos valores ainda não salvos e sem `float` binário;
- migrations incrementais de configuração e relação Compra–Resgate, além de OpenAPI e documentação atualizados;
- validação final com 103 testes focados e 556 testes na suíte completa aprovados, além de `manage.py check`, `makemigrations --check`, validator da conversão de Resgate e `git diff --check`.

Com a F3.06A–F3.06F integrada, o domínio e a API da rodada estão reconciliados. A Issue guarda-chuva #62 permanece aberta até a conclusão do Seed FATECalçados V2 (#72) e a revalidação do cenário de demonstração.

## Fase 4 — Dados e visualização

### F4.01 — Seed determinístico e coerente ✅ P0

Issue: #58. PR: #59.

Entregue:

- management command `seed_fatecalcados --data-base YYYY-MM-DD`;
- data-base obrigatória com referência `T` às 12:00 em `America/Sao_Paulo`;
- cenário one-shot por banco de demonstração, sem `reset`, `TRUNCATE` ou exclusão destrutiva;
- 1 Empresa FATECalçados, 12 Lojas, 36 Clientes, 300 Compras e 300 Lotes;
- níveis Bronze/Prata/Ouro configurados como dados do tenant em `0 / 1000 / 5000`, sem benefício automático;
- uma campanha `2x` com 24 aplicações históricas geradas pelo motor real;
- 8 Resgates reais, com consumo FEFO e 22 alocações no cenário de referência;
- Compras, Lotes, campanhas, Resgates e alocações criados pelos services reais do domínio;
- simulação temporal restrita ao seed para os Resgates históricos, sem alterar API ou contrato operacional da F3.04;
- proteção contra colisões e reexecução, com pré-checagem, `pg_advisory_xact_lock` e segunda verificação sob o lock;
- rollback integral em qualquer falha intermediária ou divergência da validação final;
- personagens narrativos para demonstrar nível ≠ saldo ≠ atividade, expiração, campanha e FEFO;
- `docs/SEED_FATECALCADOS.md` documentando composição, execução, determinismo, recriação e limitações;
- nenhuma migration nova e nenhum contrato F3.01–F3.05 alterado;
- validação local com 17 testes focais e 426 testes totais, além de `check`, `makemigrations --check --dry-run`, OpenAPI, `git diff --check` e `uv lock --check`.

A modelagem de dados vigente também está consolidada em `docs/MODELAGEM_DE_DADOS.md`, separando entidades persistidas de informações derivadas como saldo, pontos para nível, nível atual e atividade.

### F4.01B — Seed FATECalçados V2 🟡 P0

Issue: #72.

Próxima etapa da rodada F3.06/F4.01.

Objetivo:

- evoluir o cenário one-shot já existente para demonstrar os contratos integrados da F3.06;
- manter 12 Lojas e criar Clientes ativos/inativos, níveis com benefícios, retorno, campanha, Resgate/FEFO, expiração, estorno e dados coerentes para o Dashboard;
- criar contas demo estáveis de Administrador, Gestor com exatamente duas Lojas e Cliente narrativo;
- disponibilizar a credencial de integração do ambiente de demonstração por mecanismo operacional seguro, sem hardcode ou exposição pública do segredo;
- preservar services reais, determinismo, rollback integral e `RETORNA_SEED_SENHA` como única fonte da senha demo.

### F4.02 — Dashboard do Gestor ⏳ P0

O Dashboard continua sendo a entrega central da F4.02. Antes dele, o Seed FATECalçados V2 (#72) deve reconciliar o banco de demonstração com o domínio/API já integrados e fornecer dados coerentes para os indicadores.

#### F4.02A — Base visual mínima + SCSS ✅ P0

Issue: #54. PR: #63.

Entregue:

- frontend server-rendered com Django Templates, mantendo a regra de negócio e autorização no backend;
- Vite + Sass para build de assets e integração seletiva do Gentelella 4.2.0, sem SPA/React;
- shell de Gestão responsivo com sidebar, rail desktop, drawer mobile, topbar e breadcrumbs;
- navegação administrativa limitada às superfícies realmente autorizadas para Administrador e Gestor;
- páginas públicas Home e Para empresas com rotas reais e linguagem de produto;
- preferências locais de tema Automático/Claro/Escuro, escala de texto 100/110/120% e modo de formulários;
- formulários compostos com progressive enhancement e funcionamento completo sem JavaScript;
- tabelas semânticas no desktop e cards equivalentes no mobile a partir da mesma coleção server-side;
- Storyset restrito ao onboarding inicial, com variantes light/dark locais e atribuição preservada;
- foco visível, reduced motion, forced-colors, alvos de interação mínimos e estados sem depender somente de cor;
- documentação do frontend em `docs/FRONTEND.md` e testes estruturais em `apps.empresas.test_interface`;
- validação local com validator Node, `npm ci`, build Vite, staticfiles, `check`, `makemigrations --check --dry-run`, OpenAPI, `uv lock --check`, `git diff --check` e 455 testes totais aprovados.

`Criar empresa` permanece como ação de onboarding/contexto, fora da navegação operacional geral. O Cliente continua sem shell administrativo. A F4.02A não introduziu Dashboard nem alterou regras de domínio, models, migrations ou contratos da API.

#### F4.02B — Dashboard funcional ⏳ P0

Objetivo: entregar os indicadores essenciais calculados sobre a vertical real.

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
- Gestor: somente Lojas autorizadas.

#### F4.02C — Gráficos, filtros e refinamentos do Dashboard ⏳ P0

Objetivo: consolidar a leitura operacional da F4.02 após os indicadores funcionais.

Direção:

- gráficos de linha/barra para evolução temporal e demais visualizações que agreguem leitura real;
- filtros por período e Loja quando aplicável;
- refinamento dos cards/tabelas do Dashboard sem duplicar regra de negócio no frontend;
- manter toda autorização e cálculo de domínio no backend.

### F4.03 — Área do Cliente ⏳ P1

Direção:

- saldo;
- pontos próximos de expirar;
- nível e benefícios somente quando cada capacidade estiver implementada;
- histórico de compras/pontos;
- histórico de resgates.

Interface mobile-first e separada visualmente do painel administrativo.

## Fase 5 — Qualidade da entrega

### F5.01 — Acessibilidade e acabamento ⏳ P1

A F4.02A já entregou a base responsiva, temas claro/escuro/automático, escala de texto, foco visível, reduced motion e forced-colors. A F5.01 concentra o refinamento que não precisa bloquear a vertical P0:

- auditoria e correção fina de responsividade nas superfícies finais;
- validação ampliada de navegação por teclado e tecnologias assistivas;
- refinamento de contraste, mensagens, estados e hierarquia visual conforme o produto completo;
- ajustes de alto contraste e forced-colors em casos especiais identificados durante a validação final;
- acabamento de densidade, espaçamento e consistência visual após Dashboard e Área do Cliente.

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
Cliente resgata pontos
↓
Cliente é classificado
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
- base visual mínima necessária ao Dashboard;
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

Se uma ideia nova colocar em risco Empresa → Loja → Configuração → API → Compra → Pontos → Evento → Resgate → Níveis → Dashboard, ela deve ser classificada como P1 ou P2.