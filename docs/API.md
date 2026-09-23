# API do Produto

## Objetivo

A API REST é uma interface de primeira classe do DataSystemChallenge. Ela existe para permitir integração com PDVs, ERPs, e-commerces, aplicativos e outros consumidores externos sem duplicar as regras de fidelidade.

A API utiliza Django REST Framework sobre a mesma camada de domínio utilizada pela interface web.

A F2.06 implementa somente a fundação: credenciais de integração, health, contexto e OpenAPI. Compra, idempotência de Compra, Cliente por API, Resgate, LotePontos, cálculo de fidelidade, campanhas/eventos e níveis permanecem futuros; os exemplos desses fluxos abaixo não são endpoints disponíveis.

```text
Django Templates ─┐
                  ├── Camada de domínio/serviços ─── PostgreSQL
REST API / DRF ───┘
```

A API não deve possuir uma segunda implementação de cálculo de pontos, resgate, parâmetros ou campanhas.

## Princípios

1. toda API pública é versionada;
2. contratos externos são tratados como estáveis;
3. serializers representam contratos externos e não são equivalentes automaticamente aos models;
4. consumidores externos enviam fatos da operação; o domínio calcula fidelidade;
5. credenciais de integração possuem escopo de Empresa e, quando necessário, de Loja;
6. operações suscetíveis a retry precisam ser idempotentes;
7. respostas e erros seguem formato consistente;
8. isolamento multiempresa é validado no backend;
9. OpenAPI faz parte da entrega;
10. documentação de fluxo complementa a documentação automática.

## Versionamento

A primeira versão utiliza prefixo:

```text
/api/v1/
```

Endpoints implementados:

```text
/api/v1/health/
/api/v1/contexto/
```

Alterações incompatíveis de contrato devem resultar em nova versão, em vez de quebrar silenciosamente consumidores existentes.

## Consumidores

Existem dois grupos conceituais de consumidores.

### Usuários humanos

- Cliente;
- Gestor;
- Administrador da Empresa.

Esses usuários podem utilizar a interface web e, futuramente, endpoints específicos conforme necessidade.

### Integrações de sistema

- PDV;
- ERP;
- e-commerce;
- aplicativo externo;
- terminal de Loja.

Integrações possuem `CredencialIntegracao`, não `Usuario`. A autenticação disponibiliza a credencial em `request.auth`, sem criar ou autenticar uma identidade humana.

## Autenticação de integração

O header obrigatório nos endpoints protegidos é:

```http
X-API-Key: <identificador>.<segredo>
```

O identificador é público, aleatório e único. O segredo é gerado com `secrets.token_urlsafe(32)` e somente seu hash, produzido pelos hashers do Django, é persistido. O identificador é gerado independentemente com `secrets.token_urlsafe(18)`.

A chave completa é retornada pelo service e exibida **somente na resposta de criação**. Não é armazenada em sessão, messages, logs ou atributo do model, nem pode ser recuperada posteriormente. A tela usa `Cache-Control: no-store` e `Referrer-Policy: no-referrer`.

Modelagem implementada em `apps.empresas`:

```text
CredencialIntegracao
├── empresa
├── nome
├── identificador
├── segredo_hash
├── escopo
├── ativa
├── criada_por -> MembroEmpresa
├── criada_em
└── ultimo_uso_em

CredencialAcessoLoja
├── credencial
└── loja
```

Header ausente ou malformado, identificador inexistente, segredo incorreto e credencial inativa recebem o mesmo `401`, sem distinguir publicamente a causa:

```json
{
  "erro": {
    "codigo": "credencial_invalida",
    "mensagem": "Credencial de integração inválida."
  }
}
```

O header de resposta é `WWW-Authenticate: X-API-Key`. Após autenticação válida, `ultimo_uso_em` é atualizado. Falhas de autenticação não alteram esse campo. Autenticação e desativação usam transações e bloqueiam a mesma credencial; registrar uso não reativa uma credencial desativada.

Sessão Django, BasicAuthentication e CSRF não autenticam a API. A chave deve ser enviada no header, não na URL/query string. Use HTTPS em produção e não registre o header nem o corpo da resposta web que contém a chave.

## Provisionamento administrativo web

Somente um `ADMINISTRADOR` ativo no contexto da Empresa pode executar:

| Método | Rota | Operação |
| --- | --- | --- |
| GET | `/gestao/integracoes/` | Listar credenciais da Empresa ativa |
| GET/POST | `/gestao/integracoes/nova/` | Preencher formulário/criar credencial |
| POST | `/gestao/integracoes/<id>/desativar/` | Desativar sem excluir |

A criação solicita nome, escopo e Lojas apenas para `LOJAS`. A Empresa e o criador vêm do contexto autenticado; IDs enviados pelo navegador não os substituem. O queryset e o service restringem a seleção à Empresa ativa. A criação da credencial e de seus acessos é transacional.

A listagem mostra nome, identificador público, escopo, estado, criação e último uso; nunca mostra segredo nem `segredo_hash`. Gestores e membros inativos recebem `403`. Os POSTs web continuam exigindo CSRF; GET na desativação recebe `405`.

Desativar preserva o registro e impede novas autenticações. Não há exclusão, reativação ou rotação na interface. Se o segredo for perdido ou for necessário mudar o escopo, desative a credencial antiga e crie uma nova.

## Escopo e isolamento

Uma credencial da Empresa A nunca pode consultar ou criar recursos da Empresa B.

Os escopos implementados são:

- `EMPRESA`: todas as Lojas atuais e futuras da própria Empresa, sem relações individuais em `CredencialAcessoLoja`;
- `LOJAS`: uma ou mais Lojas explicitamente vinculadas, todas da própria Empresa. A criação sem Lojas é rejeitada.

Empresa e escopo são imutáveis após a criação pelos caminhos normais do domínio. As relações usam `PROTECT`, e o par credencial/Loja é único. Models validam relações cross-tenant e rejeitam acessos individuais para `EMPRESA`; o service garante `1..N` Lojas na criação transacional.

`lojas_autorizadas(credencial)` e `exigir_loja_autorizada(credencial, loja)` ficam em `apps.empresas.services` para reutilização pelos endpoints futuros. Reconsultam o estado persistido e filtram sempre pela Empresa. Objetos adulterados em memória e relações cross-tenant inseridas fora do fluxo normal não ampliam acesso. Credenciais inativas não recebem Lojas autorizadas.

Como no restante do domínio, `QuerySet.update`, operações bulk e SQL bruto podem contornar validações do model; não são caminhos normais para alterar invariantes. Não há triggers de banco.

Quando o endpoint de Compra existir, uma credencial limitada à Loja Araras não poderá registrar compra na Loja Campinas.

A regra de autorização deve ser aplicada no backend, independentemente do identificador recebido pela URL ou pelo payload.

```text
credencial
↓
Empresa autorizada
↓
Loja autorizada?
├── sim -> continuar
└── não -> 403
```

## Responsabilidade pelo cálculo — futuro

O consumidor externo envia os fatos necessários da venda. Ele não envia o resultado calculado da fidelidade como fonte de verdade.

Exemplo correto:

```json
{
  "identificador_externo": "VENDA-000123",
  "cliente_cpf": "52998224725",
  "valor": "149.90",
  "realizada_em": "2026-09-22T14:31:00-03:00"
}
```

A plataforma:

1. identifica a Empresa/Loja através da credencial e do contexto permitido;
2. identifica o Cliente;
3. resolve a configuração efetiva da Empresa/Loja;
4. identifica eventos/campanhas aplicáveis;
5. calcula pontos e benefícios;
6. persiste a operação e seus snapshots;
7. retorna o resultado.

Não deve existir um contrato em que o PDV determine arbitrariamente `pontos_concedidos` como fonte de verdade.

## Compra e idempotência — futuro

Integrações podem repetir uma requisição por timeout, perda de conexão ou retry automático. A mesma venda não pode gerar pontos duas vezes.

Cada venda externa deve possuir um identificador estável, por exemplo:

```text
identificador_externo = VENDA-000123
```

A identidade da operação deve ser única dentro do escopo adequado, por exemplo:

```text
Loja + identificador_externo
```

ou outro escopo definido pela integração.

Fluxo esperado:

```text
PDV envia VENDA-000123
↓
Compra criada e pontos concedidos
↓
resposta se perde
↓
PDV reenvia VENDA-000123
↓
plataforma reconhece a operação existente
↓
não duplica Compra nem pontos
```

A política exata de resposta ao retry será definida junto ao endpoint de Compra.

## Contrato externo e serializers

O model interno não é automaticamente o contrato público.

```text
Model
- campos internos
- auditoria
- snapshots
- relações técnicas

Serializer/API
- somente campos necessários ao consumidor
- nomes estáveis
- validação do contrato
```

Mudanças internas no banco não devem obrigatoriamente quebrar a API.

## Erros

A API utiliza um envelope consistente para erros tratados:

Exemplo:

```json
{
  "erro": {
    "codigo": "credencial_invalida",
    "mensagem": "Credencial de integração inválida."
  }
}
```

Mapeamento implementado:

| HTTP | Código | Mensagem |
| --- | --- | --- |
| 400 | `requisicao_invalida` | Dados inválidos. |
| 401 | `credencial_invalida` | Credencial de integração inválida. |
| 403 | `acesso_negado` | Acesso negado. |
| 404 | `nao_encontrado` | Recurso não encontrado. |
| 405 | `metodo_nao_permitido` | Método não permitido. |
| 406 | `formato_nao_aceito` | Formato de resposta não aceito. |
| 415 | `formato_nao_suportado` | Formato de conteúdo não suportado. |

O 404 também cobre URLs inexistentes dentro de `/api/`. Erros de validação podem acrescentar detalhes por campo:

```json
{
  "erro": {
    "codigo": "requisicao_invalida",
    "mensagem": "Dados inválidos.",
    "detalhes": {"nome": ["Campo obrigatório."]}
  }
}
```

Exceções internas inesperadas são relançadas pelo DRF para preservar logging/reporting e a semântica `500` do Django. Não são convertidas em `200` ou `400`. Com `DEBUG=False`, a resposta padrão do Django não expõe traceback, SQL ou detalhes internos; não há contrato de envelope JSON para essas falhas inesperadas. `DEBUG` deve permanecer desabilitado em produção.

Códigos de negócio possíveis no futuro incluem:

- `loja_fora_do_escopo`;
- `cliente_nao_encontrado`;
- `compra_duplicada`;
- `saldo_insuficiente`;
- `resgate_invalido`;
- `campanha_conflitante`.

Esses códigos futuros ainda não fazem parte do contrato implementado.

## Status HTTP

Semântica HTTP; criação de recursos e conflitos de operações de negócio são futuros:

```text
200 OK
- consulta ou operação idempotente bem-sucedida

201 Created
- recurso criado

400 Bad Request
- payload ou regra de entrada inválida

401 Unauthorized
- credencial ausente ou inválida

403 Forbidden
- autenticado, porém fora do papel/escopo permitido

404 Not Found
- recurso inexistente no escopo autorizado

409 Conflict
- conflito de estado ou duplicidade quando semanticamente aplicável
```

A API deve manter consistência em vez de utilizar códigos diferentes para o mesmo tipo de situação.

## Endpoints de negócio prioritários — futuros

A entrega de uma semana deve priorizar poucos endpoints com comportamento completo.

Direção inicial:

```text
GET  /api/v1/clientes/por-cpf/{cpf}/
GET  /api/v1/clientes/{id}/saldo/
POST /api/v1/compras/
POST /api/v1/resgates/
```

Os endpoints de Cliente, Compra e Resgate acima são direção de produto, não estão disponíveis e não aparecem no OpenAPI. Cada endpoint deve ganhar critérios de aceite antes da implementação.

Endpoints administrativos adicionais podem ser expostos somente quando houver necessidade real.

## Configuração efetiva — futuro

Pode existir futuramente um endpoint de leitura da configuração efetiva de uma Loja, por exemplo:

```text
GET /api/v1/lojas/{id}/configuracao-efetiva/
```

Esse endpoint serve para transparência e integração, mas o PDV não deve depender dele para recalcular a fidelidade localmente. A fonte de verdade do cálculo permanece na plataforma.

## OpenAPI

A documentação técnica é gerada pelo `drf-spectacular`, com `DEFAULT_SCHEMA_CLASS = drf_spectacular.openapi.AutoSchema`.

As três rotas são públicas no MVP:

```text
/api/schema/      -> OpenAPI JSON/YAML
/api/docs/        -> Swagger UI
/api/redoc/       -> ReDoc
```

O schema pode ser obtido como JSON com `Accept: application/vnd.oai.openapi+json`; YAML também está disponível. Ele descreve somente health e contexto, sem endpoints futuros.

O security scheme se chama `X-API-Key`, com `type: apiKey`, `in: header` e `name: X-API-Key`. Health não exige autenticação; contexto exige esse scheme. No Swagger, use **Authorize** e informe a chave completa `<identificador>.<segredo>` para testar o contexto. A autorização não é persistida pelo Swagger entre carregamentos. Documentação pública não concede acesso aos dados.

## Documentação conceitual

OpenAPI descreve o contrato, mas não substitui documentação de integração.

A documentação deve explicar pelo menos:

- autenticação;
- escopo Empresa/Loja;
- fluxo de integração com PDV;
- idempotência;
- códigos de erro;
- exemplos de request/response;
- versionamento;
- limites conhecidos.

Documentação futura pode ser separada em:

```text
docs/api/
├── README.md
├── AUTENTICACAO.md
├── INTEGRACAO_PDV.md
├── IDEMPOTENCIA.md
├── ERROS.md
└── EXEMPLOS.md
```

A estrutura só deve ser expandida quando houver conteúdo suficiente para justificar arquivos separados.

## Exemplo de integração com PDV — fluxo futuro

```text
1. Empresa é cadastrada
2. Administrador cria Loja
3. integração recebe credencial com escopo adequado
4. Cliente é identificado por CPF
5. PDV conclui uma venda
6. PDV chama POST /api/v1/compras/
7. API valida credencial e escopo
8. domínio resolve parâmetros e eventos
9. domínio calcula pontos
10. Compra/LotePontos são persistidos
11. API retorna o resultado
12. dashboard passa a refletir a operação
```

## Segurança

Prioridades mínimas:

- HTTPS em produção;
- segredos de integração fora do código e dos logs;
- armazenamento seguro das credenciais;
- revogação/desativação de credenciais;
- validação estrita de payloads;
- isolamento multiempresa no backend;
- minimização da exposição de CPF e outros dados pessoais;
- rate limiting quando a infraestrutura da entrega permitir;
- auditoria de operações críticas quando priorizada.

## CPF e dados pessoais

CPF pode ser necessário para identificar Cliente em integrações, mas não deve ser devolvido integralmente em toda resposta ou listagem sem necessidade.

O contrato de cada endpoint deve expor somente os dados necessários ao caso de uso.

## Testes da API

Na F2.06, a cobertura adicionada está em `apps/api/tests.py`, `apps/empresas/test_integracoes.py` e `apps/empresas/test_migration_integracoes.py`: autenticação, escopo, provisionamento web, CSRF, contrato de erros, OpenAPI e preservação dos dados na migration incremental `0007` → `0008`.

Os endpoints de negócio futuros também deverão ter testes para:

- credencial válida;
- credencial inválida;
- escopo correto de Empresa;
- escopo correto de Loja;
- tentativa cross-tenant;
- payload inválido;
- CPF inválido/malformado quando aplicável;
- operação válida;
- retry/idempotência de Compra;
- aplicação de configuração herdada;
- aplicação de override da Loja;
- aplicação de Evento quando o motor correspondente existir.

O teste de isolamento entre Empresas é requisito prioritário para qualquer endpoint multiempresa.

## Health check

A API expõe:

```text
GET /api/v1/health/
```

É público, responde `200` com exatamente:

```json
{"status": "ok"}
```

Não consulta o banco nem expõe versões, DEBUG, caminhos, tenant ou segredos. Valida disponibilidade básica da aplicação, não a disponibilidade do banco.

## Contexto da integração

```http
GET /api/v1/contexto/
X-API-Key: <identificador>.<segredo>
```

Exemplo ilustrativo de resposta `200`:

```json
{
  "credencial": {"identificador": "<identificador-publico>", "nome": "PDV"},
  "empresa": {"id": 1, "nome": "Empresa"},
  "escopo": "EMPRESA",
  "lojas": [{"id": 1, "nome": "Centro", "cidade": "Araras"}]
}
```

Para `EMPRESA`, a lista reflete todas as Lojas atuais do tenant, inclusive criadas após a credencial. Para `LOJAS`, inclui somente as explicitamente relacionadas. A ordenação é por nome e depois ID. Não são expostos segredo, hash, CPF ou CNPJ. Sem chave válida, a resposta é o `401` genérico. A resposta autenticada não deve ser armazenada em cache.

## Prioridade para a entrega de uma semana — vertical futura

A API deve demonstrar uma vertical integrada, não uma grande quantidade de CRUDs superficiais.

Exemplo de demonstração desejada:

```text
Empresa configura 1 ponto por R$1
↓
Loja herda a configuração
↓
Evento Black Friday = 2x
↓
PDV envia Compra de R$200 pela API
↓
backend calcula 400 pontos
↓
resposta documentada no Swagger/OpenAPI
↓
dashboard reflete a operação
```

Essa vertical demonstra produto, parametrização, integração, domínio e observabilidade do resultado em um único fluxo.

## Fora do objetivo inicial

Não é prioridade para a primeira entrega:

- criar microserviços;
- expor todos os models como CRUD;
- implementar OAuth2 completo sem necessidade concreta;
- permitir que o PDV calcule a fidelidade como fonte de verdade;
- criar múltiplas versões da API antes de existir incompatibilidade;
- expor operações administrativas somente para “ter mais endpoints”.
