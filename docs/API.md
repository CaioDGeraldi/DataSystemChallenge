# API do Produto

## Objetivo

A API REST é uma interface de primeira classe do DataSystemChallenge. Ela existe para permitir integração com PDVs, ERPs, e-commerces, aplicativos e outros consumidores externos sem duplicar as regras de fidelidade.

A direção é utilizar Django REST Framework sobre a mesma camada de domínio utilizada pela interface web.

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

Exemplos:

```text
/api/v1/clientes/
/api/v1/compras/
/api/v1/resgates/
/api/v1/lojas/
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

Integrações não devem ser representadas como se fossem usuários humanos comuns.

## Autenticação de integração

Para a entrega inicial, a direção é utilizar credenciais próprias de integração, com escopo explícito.

Exemplo conceitual:

```text
CredencialApi
├── empresa
├── nome
├── identificador
├── segredo/hash
├── ativa
├── criada_em
└── ultimo_uso_em
```

Uma credencial pode ser:

- corporativa, operando nas Lojas permitidas da Empresa;
- restrita a uma Loja ou conjunto de Lojas.

O desenho definitivo da credencial deve ser fechado em Issue própria antes da implementação.

## Escopo e isolamento

Uma credencial da Empresa A nunca pode consultar ou criar recursos da Empresa B.

Uma credencial limitada à Loja Araras não pode registrar compra na Loja Campinas.

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

## Responsabilidade pelo cálculo

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

## Compra e idempotência

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

A API deve possuir formato consistente para erros de negócio.

Exemplo:

```json
{
  "erro": {
    "codigo": "cliente_nao_encontrado",
    "mensagem": "Cliente não encontrado."
  }
}
```

Códigos possíveis no futuro incluem:

- `credencial_invalida`;
- `loja_fora_do_escopo`;
- `cliente_nao_encontrado`;
- `compra_duplicada`;
- `saldo_insuficiente`;
- `resgate_invalido`;
- `campanha_conflitante`.

A lista real deverá refletir somente regras implementadas.

## Status HTTP

Direção inicial:

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

## Endpoints prioritários

A entrega de uma semana deve priorizar poucos endpoints com comportamento completo.

Direção inicial:

```text
GET  /api/v1/health/
GET  /api/v1/clientes/por-cpf/{cpf}/
GET  /api/v1/clientes/{id}/saldo/
POST /api/v1/compras/
POST /api/v1/resgates/
```

A lista é uma direção de produto, não um contrato já implementado. Cada endpoint deve ganhar critérios de aceite antes da implementação.

Endpoints administrativos adicionais podem ser expostos somente quando houver necessidade real.

## Configuração efetiva

Pode existir futuramente um endpoint de leitura da configuração efetiva de uma Loja, por exemplo:

```text
GET /api/v1/lojas/{id}/configuracao-efetiva/
```

Esse endpoint serve para transparência e integração, mas o PDV não deve depender dele para recalcular a fidelidade localmente. A fonte de verdade do cálculo permanece na plataforma.

## OpenAPI

A documentação técnica da API deve ser derivada de um schema OpenAPI.

A direção é utilizar Django REST Framework com geração automática de schema, preferencialmente com `drf-spectacular` ou solução equivalente definida no momento da implementação.

A entrega deve disponibilizar rotas equivalentes a:

```text
/api/schema/      -> OpenAPI JSON/YAML
/api/docs/        -> Swagger UI
/api/redoc/       -> ReDoc
```

Os caminhos exatos podem ser ajustados, mas as três capacidades devem existir:

- schema consumível por ferramentas;
- documentação interativa;
- documentação navegável para leitura.

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

## Exemplo de integração com PDV

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

## Testes obrigatórios da API

A API deve possuir testes automatizados para os comportamentos críticos, incluindo:

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

A API deve expor um endpoint simples de saúde, por exemplo:

```text
GET /api/v1/health/
```

Seu objetivo é permitir validação de deploy e disponibilidade básica. Ele não deve expor segredos ou detalhes internos desnecessários.

## Prioridade para a entrega de uma semana

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
