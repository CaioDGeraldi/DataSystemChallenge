# API do Produto

## Objetivo

A API REST é uma interface de primeira classe do DataSystemChallenge. Ela existe para permitir integração com PDVs, ERPs, e-commerces, aplicativos e outros consumidores externos sem duplicar as regras de fidelidade.

A API utiliza Django REST Framework sobre a mesma camada de domínio utilizada pela interface web.

A F2.06 entrega credenciais de integração, health, contexto e OpenAPI. A F3.01 acrescenta registro de Compra e idempotência; a F3.02 acrescenta cálculo base de pontos e LotePontos histórico. A F3.03 acrescenta campanhas temporárias com multiplicador de pontos. A F3.04 acrescenta Resgate idempotente com consumo de Lotes e desconto histórico. A F3.06B acrescenta consulta autenticada do estado atual de fidelidade do Cliente para integrações.

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
GET  /api/v1/health/
GET  /api/v1/contexto/
GET  /api/v1/clientes/fidelidade/
POST /api/v1/compras/
POST /api/v1/resgates/
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

`lojas_autorizadas(credencial)` e `exigir_loja_autorizada(credencial, loja)` ficam em `apps.empresas.services` e são reutilizados pelos registros de Compra e Resgate. Reconsultam o estado persistido e filtram sempre pela Empresa. Objetos adulterados em memória e relações cross-tenant inseridas fora do fluxo normal não ampliam acesso. Credenciais inativas não recebem Lojas autorizadas.

Como no restante do domínio, `QuerySet.update`, operações bulk e SQL bruto podem contornar validações do model; não são caminhos normais para alterar invariantes. Não há triggers de banco.

Uma credencial limitada à Loja Araras não pode registrar Compra na Loja Campinas.

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
  "loja_id": 1,
  "identificador_externo": "VENDA-000123",
  "cliente_cpf": "52998224725",
  "valor": "149.90",
  "ocorrida_em": "2026-09-22T14:31:00-03:00"
}
```

A plataforma:

1. identifica a Empresa/Loja através da credencial e do contexto permitido;
2. identifica o Cliente;
3. resolve a configuração efetiva da Empresa/Loja;
4. identifica eventos/campanhas aplicáveis;
5. aplica o multiplicador e calcula a concessão de pontos;
6. persiste a operação e seus snapshots;
7. retorna o resultado.

Não deve existir um contrato em que o PDV determine arbitrariamente `pontos_concedidos` como fonte de verdade.

## Consulta de fidelidade do Cliente — F3.06B

```http
GET /api/v1/clientes/fidelidade/?loja_id=1&cliente_cpf=52998224725
X-API-Key: <identificador>.<segredo>
```

A consulta entrega ao PDV o estado atual de fidelidade sem transferir regras de negócio para o consumidor. `loja_id` e `cliente_cpf` são obrigatórios. A Loja deve estar no escopo da credencial e o Cliente deve pertencer à mesma Empresa.

A resposta contém:

- identificação mínima do Cliente;
- situação ativo/inativo e última Compra;
- pontos históricos usados para classificação;
- nível atual e benefícios configurados;
- indicação de aplicabilidade atual dos benefícios do nível;
- saldo de pontos utilizável;
- promoção de retorno, somente quando aplicável;
- parâmetros de Resgate relevantes ao caixa.

Exemplo:

```json
{
  "cliente": {
    "cpf": "52998224725",
    "nome": "Ana Silva"
  },
  "atividade": {
    "ativo": true,
    "ultima_compra_em": "2026-09-23T10:30:00-03:00",
    "periodo_cliente_ativo_dias": 180
  },
  "nivel": {
    "pontos_historicos": "1240.0000",
    "atual": {
      "nome": "Prata",
      "pontos_minimos": "1000.0000",
      "beneficios": {
        "bonus_pontos_percentual": "10.0000",
        "desconto_percentual": "5.0000",
        "aplicaveis": true
      }
    }
  },
  "saldo": {
    "pontos": "740.0000"
  },
  "promocao_retorno": {
    "aplicavel": false,
    "bonus_pontos_percentual": "0.0000",
    "desconto_percentual": "0.0000"
  },
  "resgate": {
    "minimo_pontos": 100,
    "incremento_pontos": 50,
    "valor_monetario_por_ponto": "0.05"
  }
}
```

`nivel.pontos_historicos` soma todas as concessões históricas do Cliente, inclusive Lotes expirados ou já consumidos. Portanto, expiração e Resgate não reduzem a classificação de nível.

`saldo.pontos` representa o valor utilizável no instante da consulta: considera somente Lotes ainda não expirados e desconta pontos já alocados em Resgates.

Quando não existir nível compatível, `nivel.atual` é `null`, mas `nivel.pontos_historicos` continua presente.

Atividade, retorno e aplicabilidade dos benefícios reutilizam a avaliação canônica do domínio. Cliente sem Compra anterior não é considerado retorno. Em caso de inatividade, a política de primeira Compra após inatividade determina se os benefícios de nível seriam aplicáveis naquele instante.

A promoção de retorno só é marcada como aplicável quando o Cliente está efetivamente em retorno e a promoção corporativa está ativa. Caso contrário, seus percentuais retornam zero.

A consulta é somente leitura, usa o instante do servidor, não cria snapshots e não garante o mesmo estado para uma operação posterior. Compra ou Resgate efetivos devem recalcular e revalidar todas as regras.

Loja inexistente ou não autorizada retorna `403 loja_fora_do_escopo`. Cliente inexistente ou pertencente somente a outro tenant retorna `404 cliente_nao_encontrado`, sem revelar informação externa.

A resposta utiliza `Cache-Control: no-store`.

## Compra, idempotência e fidelidade — F3.01/F3.02/F3.03

```http
POST /api/v1/compras/
X-API-Key: <identificador>.<segredo>
Content-Type: application/json
```

```json
{
  "loja_id": 1,
  "identificador_externo": "VENDA-000123",
  "cliente_cpf": "52998224725",
  "valor": "199.90",
  "ocorrida_em": "2026-09-23T10:30:00-03:00"
}
```

Todos os campos são obrigatórios:

| Campo | Contrato |
| --- | --- |
| `loja_id` | ID positivo de Loja autorizada pela credencial. Loja externa, não autorizada ou inexistente recebe `403 loja_fora_do_escopo`. |
| `identificador_externo` | String de até 255 caracteres após `strip()` nas extremidades; não pode ficar vazia. Preserva case, espaços e conteúdo interno. |
| `cliente_cpf` | CPF normalizado/validado pela regra existente. Resolve a identidade global e o Cliente da Empresa da Loja. Não cria vínculo nem altera Usuario. Sem Cliente no tenant: `404 cliente_nao_encontrado`. |
| `valor` | Decimal positivo com até duas casas decimais: `0.01` a `9999999999.99`. Envie string decimal, nunca float. Não há arredondamento de valores com casas excedentes. |
| `ocorrida_em` | ISO 8601 com timezone explícito. Data sem timezone é inválida. Sem limites de passado/futuro nesta fase. |

O domínio `apps.fidelidade` persiste `Compra` com Loja, Cliente, credencial de origem, identificador externo, valor, instante da venda e `criada_em` preenchido pelo servidor. Os relacionamentos usam `PROTECT`. Model e service validam coerência de tenant; a autorização reutiliza os helpers da F2.06. Para novas operações, o service cria também um LotePontos histórico, na mesma transação.

A chave idempotente é **Loja + identificador_externo**, protegida por `UniqueConstraint` no PostgreSQL. O mesmo identificador pode existir em outra Loja. O valor usa `DecimalField(max_digits=12, decimal_places=2)` e possui constraint `valor > 0`.

| Situação | Resultado |
| --- | --- |
| Primeira chamada válida | Cria Compra + LotePontos atomicamente e retorna `201 Created`. |
| Mesma chave com Loja, Cliente, valor e instante equivalentes | Retorna Compra e fidelidade originais, sem recálculo, com `200 OK`. Legado sem Lote retorna `fidelidade: null`. |
| Mesma chave com Cliente, valor ou instante divergentes | Retorna `409 idempotencia_conflitante`, sem alterar ou duplicar Compra ou Lote. |

A comparação usa Cliente resolvido, valor Decimal e instante timezone-aware. Offsets diferentes que representam o mesmo instante são equivalentes. Outro consumidor autorizado para a mesma Loja pode repetir a operação: `credencial_origem`, `criada_em` e os demais fatos originais são preservados, inclusive quando a credencial de origem foi desativada posteriormente.

`registrar_compra()` executa a operação em transação. O INSERT ocorre em savepoint; em disputa, somente a violação da constraint da chave idempotente é recuperada para consultar a Compra vencedora e comparar os fatos. Somente a operação vencedora resolve a configuração e cria o Lote antes do commit da transação externa. Qualquer falha na concessão desfaz também a nova Compra. Requests equivalentes convergem para uma Compra e um Lote; divergentes resultam em uma criação e um conflito. Outras falhas de integridade não são ocultadas. A estratégia utiliza a constraint imediata e o isolamento padrão READ COMMITTED do PostgreSQL configurado pelo Django.

Resposta ilustrativa com taxa padrão de 1,00 ponto/R$, precisão 2 e HALF_UP; o mesmo histórico é retornado em `201` e no retry `200`:

```json
{
  "id": 123,
  "identificador_externo": "VENDA-000123",
  "loja": {"id": 1, "nome": "Centro"},
  "cliente": {"cpf": "52998224725"},
  "valor": "199.90",
  "ocorrida_em": "2026-09-23T10:30:00-03:00",
  "criada_em": "2026-09-23T10:30:02-03:00",
  "fidelidade": {
    "pontos_base": "199.9000",
    "pontos_concedidos": "199.9000",
    "expira_em": "2027-09-23T10:30:00-03:00"
  }
}
```

A resposta expõe somente esses campos, com valor monetário em string de duas casas. O bloco `fidelidade` expõe apenas pontos base, pontos concedidos (strings decimais com exatamente quatro casas) e expiração. Não retorna segredo, hash, senha, credencial completa ou os demais snapshots internos. Nesta fase não há GET/listagem, edição, cancelamento, estorno ou exclusão de Compra pela API.

## Motor de pontos e histórico — F3.02

O PDV envia fatos da venda; pontos enviados no payload não definem a concessão. A plataforma resolve `pontos_por_real` pelo padrão do produto → Empresa → override permitido da Loja.

Dois parâmetros são configuráveis **somente por Empresa**, na tela administrativa já existente, por Administrador ativo:

| Parâmetro | Valores | Default |
| --- | --- | --- |
| `precisao_pontos` | `0`, `1`, `2`, `4` | `2` |
| `modo_arredondamento_pontos` | `HALF_UP`, `DOWN`, `UP` | `HALF_UP` |

A Loja continua podendo sobrescrever apenas `pontos_por_real`. Models e constraints rejeitam políticas fora dos conjuntos permitidos.

```text
pontos_base = Compra.valor × pontos_por_real efetivo
pontos_concedidos = (pontos_base × multiplicador aplicado) quantizados pela política da Empresa
```

Toda a cadeia usa `Decimal`, sem float e sem arredondar o produto intermediário. Os campos físicos de pontos têm 24 dígitos, dos quais quatro decimais. A política de concessão não altera essa capacidade técnica.

Exemplo sem campanha: R$ 49,90 × 1,25 ponto/R$ = `62.3750` pontos base:

| Precisão | Modo | Pontos concedidos na API |
| --- | --- | --- |
| 2 | HALF_UP (metade para cima) | `"62.3800"` |
| 2 | DOWN (reduz a fração excedente) | `"62.3700"` |
| 2 | UP (aumenta se houver fração excedente) | `"62.3800"` |
| 0 | HALF_UP | `"62.0000"` |
| 1 | HALF_UP | `"62.4000"` |
| 4 | HALF_UP | `"62.3750"` |

Taxa `0.00` é válida e ainda cria um Lote com base e concessão `"0.0000"`.

Cada nova Compra registrada pelo service possui um único Lote, com relações históricas `PROTECT`. O Lote guarda Cliente exatamente igual ao da Compra, resultados, taxa aplicada, precisão, modo, validade em meses, aquisição, expiração e criação. Esses fatos são imutáveis pelos caminhos normais do model, inclusive em instâncias reconstruídas por PK e `save(update_fields=...)`. Alteração de parâmetros ou desativação da credencial de origem não invalida nem recalcula o histórico. Bulk, `QuerySet.update` e SQL bruto continuam podendo contornar validações de model.

### Aquisição e validade

`adquiridos_em` é o instante de `Compra.ocorrida_em`. A expiração soma **meses de calendário** usando `America/Sao_Paulo`, preservando horário e timezone-aware. Se o dia não existir no mês de destino, usa o último dia válido: 31/01/2027 + 1 mês → 28/02/2027; em 2028 → 29/02/2028.

Se a combinação do instante e da validade produzir uma expiração fora do intervalo representável, a operação recebe `400 requisicao_invalida` (mensagem pública `Dados inválidos.`), com rollback integral de Compra + Lote. A expiração não é truncada e a validade não é reduzida. O parâmetro continua aceitando os inteiros positivos permitidos pelo seu contrato; não foi imposto um máximo arbitrário.

Esta fase apenas registra a expiração; não implementa saldo, consumo, Resgate ou remoção automática de pontos expirados.

### Configuração no processamento e Compras legadas

A configuração aplicada é a vigente **no processamento da nova Compra**, inclusive para vendas retroativas. `ocorrida_em` determina aquisição/expiração, mas não seleciona uma configuração antiga: ainda não existe versionamento temporal de políticas. Os snapshots registram o que foi efetivamente aplicado.

Não há backfill. Compras anteriores à F3.02 podem permanecer sem Lote e recebem `"fidelidade": null`. Um retry legado não resolve política, não calcula pontos/validade e não cria Lote, mesmo se a configuração atual produzir uma expiração impossível. Qualquer backfill futuro exige operação explícita.

Retries de Compras com Lote retornam o resultado original sem recálculo, inclusive por outra credencial autorizada. Conflitos permanecem `409 idempotencia_conflitante` e preservam ambos os registros.

## Campanhas temporárias — F3.03

Campanhas modificam a concessão temporariamente, sem alterar os parâmetros permanentes. Nesta fase, somente `MULTIPLICADOR_PONTOS` é operacional. A Gestão administrativa permite listar/criar/cancelar Eventos; não há CRUD público de campanhas na API.

A aplicabilidade usa **`Compra.ocorrida_em`**, com intervalo inclusivo `inicio_em <= ocorrida_em <= fim_em`. O fim do Evento deve ser posterior ao início. Uma venda enviada depois do encerramento ainda pode receber o Evento se ocorreu no período e ele não estiver cancelado. A configuração Empresa/Loja continua sendo a vigente no processamento; não foi criado versionamento temporal dessa configuração.

Escopo `EMPRESA` abrange todas as Lojas atuais e futuras do tenant, sem relações individuais. Escopo `LOJAS` exige uma ou mais Lojas explícitas da própria Empresa. Apenas Administrador ativo pode listar, criar e cancelar; Empresa e criador vêm do contexto autenticado.

```text
Compra.valor × pontos_por_real = pontos_base (pré-campanha)
pontos_base × multiplicador = resultado exato intermediário
política corporativa aplicada uma vez = pontos_concedidos
```

Exemplo: `49.90 × 1.25 = 62.3750` base; Evento `2.0000x`; precisão 2 e HALF_UP → `124.7500` concedidos. O bloco público continua contendo somente `pontos_base`, `pontos_concedidos` e `expira_em`; nenhum snapshot de campanha foi acrescentado à resposta.

Multiplicadores usam Decimal com até 12 dígitos e quatro casas, estritamente positivos (`0.0001` a `99999999.9999`). Valores como `1.0025` e `0.5000` são válidos. O cálculo usa contexto local de 40 dígitos, suficiente para os três operandos, sem float e sem arredondamento antes da política final. Resultado final fora da capacidade `DecimalField(24, 4)` gera `400 requisicao_invalida`, sem truncamento e com rollback integral.

### Conflitos, cancelamento e concorrência

É rejeitada a criação de campanhas não canceladas com o mesmo tipo de efeito, período sobreposto e Loja efetivamente compartilhada: EMPRESA × EMPRESA, EMPRESA × LOJAS ou LOJAS × LOJAS com interseção. Fronteiras iguais também conflitam. Empresas diferentes não conflitam.

Criação, cancelamento e resolução para concessão usam o mesmo bloqueio `SELECT FOR NO KEY UPDATE` da Empresa em transações PostgreSQL. Isso serializa operações da mesma Empresa, inclusive a primeira campanha, evitando a corrida de SELECT + INSERT. Na concessão, o bloqueio permanece até o commit de Compra + Lote + aplicação. O resultado acompanha a ordem efetiva de aquisição desse bloqueio: cancelamento concluído primeiro impede aplicação; concessão concluída primeiro preserva seu histórico. A arbitragem idempotente por constraint de Compra permanece inalterada.

Nome, descrição, período, escopo, criador, Empresa, conjunto de Lojas e efeitos são imutáveis após a criação transacional. Para mudar uma campanha, cancele e crie outra. Cancelamento registra uma única transição `null → timestamp`; não permite reativação nem reescrita do instante. Eventos cancelados deixam de disputar aplicabilidade/conflitos para novas operações. Não há DELETE normal dos registros históricos.

Estados mostrados na Gestão usam o relógio atual: AGENDADO, VIGENTE, ENCERRADO e CANCELADO. Esse estado não substitui a comparação com a data da Compra.

### Proveniência e atomicidade

O Lote guarda `multiplicador_pontos_aplicado` imutável e valida sua concessão a partir desse snapshot. Lotes anteriores recebem `1.0000` pela migration, preservando os demais fatos e sem criar aplicações retroativas.

Quando há Evento, `AplicacaoEfeitoEventoLote` guarda relações protegidas com Lote, Evento e Efeito, além de tipo, valor aplicado e criação. Valida tenant, Loja, período, origem e igualdade com o multiplicador do Lote. Sem Evento, o multiplicador é `1.0000` e não há aplicação; uma campanha `1.0000x` gera aplicação, mesmo sem alterar o resultado numérico.

Compra + Lote + aplicação são uma única transação. Falha em qualquer parte desfaz a nova operação inteira. Retry equivalente não resolve Evento novamente, não recalcula e não duplica aplicação; 409 preserva todo o histórico. Cancelamento posterior não invalida Lotes nem aplicações existentes. Compra legada sem Lote continua retornando `fidelidade: null`, sem backfill.

Rotas web, com CSRF nos POSTs:

- `GET /gestao/eventos/`;
- `GET/POST /gestao/eventos/novo/`;
- `POST /gestao/eventos/<id>/cancelar/`.

Como no restante do domínio, `QuerySet.update`, bulk e SQL bruto podem contornar validações; não são caminhos normais de escrita. Nenhum trigger foi criado.

## Resgate e consumo de Lotes — F3.04

```http
POST /api/v1/resgates/
X-API-Key: <identificador>.<segredo>
Content-Type: application/json
```

```json
{
  "loja_id": 1,
  "identificador_externo": "RESGATE-001",
  "cliente_cpf": "52998224725",
  "pontos": 200
}
```

Os quatro campos são obrigatórios. `loja_id` deve identificar Loja autorizada à credencial; o CPF deve ser válido e possuir Cliente na Empresa dessa Loja. Cliente inexistente e Cliente somente de outro tenant recebem o mesmo `404 cliente_nao_encontrado`, sem criar vínculo. Loja externa, inexistente ou sem acesso recebe `403 loja_fora_do_escopo`.

`identificador_externo` exige string não vazia, com até 255 caracteres após `strip`; case e espaços internos são preservados. `pontos` exige **inteiro JSON positivo**, de 1 a `99999999999999999999`. Float (`200.0`), string (`"200"`), booleano e fração são rejeitados. Consumidores devem preservar inteiros exatos nesse intervalo, sem convertê-los a ponto flutuante. O OpenAPI não restringe o campo a `int64`.

Campos extras são rejeitados, inclusive `ocorrida_em`, `resgatado_em` ou qualquer timestamp do PDV. Cada nova operação fixa uma única vez `resgatado_em = timezone.now()` após obter o lock do Cliente. Não há backdating de Resgate.

### Regras, saldo derivado e FEFO

Aplicam-se os parâmetros efetivos atuais da Empresa (a Loja continua podendo sobrescrever somente `pontos_por_real`):

```text
pontos >= resgate_minimo_pontos
(pontos - resgate_minimo_pontos) % incremento_resgate_pontos == 0
```

Com mínimo 100 e incremento 50, são válidos 100, 150, 200 e 250. Os defaults do produto continuam sendo mínimo 100 e incremento 100.

Não existe saldo materializado. No instante T do Resgate:

```text
saldo = soma de pontos_concedidos nos Lotes com expira_em > T
        - soma das AlocacaoResgate desses Lotes
```

Em `expira_em == T`, o Lote já está expirado. A elegibilidade usa a expiração persistida, inclusive para Lotes cuja Compra possui data futura; não acrescenta um filtro por aquisição. O consumo usa `pontos_concedidos`, que já incorpora a campanha aplicada, sem recalcular campanha nem usar `pontos_base`.

FEFO é determinístico: `expira_em ASC → adquiridos_em ASC → pk ASC`. Lotes permanecem imutáveis; somente alocações registram consumo. Um Resgate de 100 pode consumir `99.7500` do Lote A e `0.2500` do Lote B. O consumo acumulado nunca pode exceder a concessão de cada Lote, e a soma das alocações deve ser exatamente o Resgate.

### Desconto e snapshots

```text
200 pontos × R$ 0,05 = R$ 10,00 de desconto
```

O domínio calcula com `Decimal` e quantiza em `0.01` usando `ROUND_HALF_UP`, independentemente do arredondamento de concessão. Com pontos inteiros e taxa de duas casas, o produto já é exato em centavos. Persistem o mínimo e o incremento (`PositiveIntegerField`), a taxa aplicada (`Decimal(12,2)`), os pontos (`Decimal(20,0)`), o desconto (`Decimal(32,2)`) e o instante. Alocações usam `Decimal(24,4)` positivo. Valores não representáveis recebem validação tratada e rollback integral, sem truncar ou saturar.

Mudanças posteriores de política ou expiração não modificam esses fatos. Resgate e alocações têm relações `PROTECT`, não admitem edição/exclusão normal e só são criados pelo service `registrar_resgate`. Seus managers públicos também rejeitam `update`, `bulk_update` e `bulk_create`; APIs internas do ORM e SQL bruto continuam fora do contrato de escrita. Não há triggers para invariantes agregadas.

### Idempotência, retries e atomicidade

| Situação | Resultado |
| --- | --- |
| Primeira operação válida | `201`, com Resgate e todas as alocações na mesma transação. |
| Mesma Loja + identificador, Cliente e pontos equivalentes | `200`, retornando o histórico original. |
| Mesma chave com Cliente ou pontos divergentes | `409 idempotencia_conflitante`. |

A chave é independente da chave de Compra. Outra Loja pode usar o mesmo identificador. Retry equivalente pode usar outra credencial atualmente autorizada, preservando a `credencial_origem` da primeira execução. Retry continua sujeito a autenticação e escopo atuais; não consulta configuração para recalcular, não calcula saldo/desconto, não reavalia expiração, não altera timestamps nem cria alocações. Após falha de rede, reenvie os mesmos fatos e a mesma chave; não gere uma nova chave para repetir a operação.

O fluxo usa PostgreSQL em READ COMMITTED: transação → autorização/normalização → `pg_advisory_xact_lock` da chave → consulta do histórico → lock do Cliente → lock dos Lotes em FEFO → configuração/saldo/desconto → Resgate e alocações → commit. A chave do advisory deriva de SHA-256 de `resgate:{loja_id}:{identificador_normalizado}`, primeiros oito bytes como inteiro signed de 64 bits. Colisão apenas serializa operações independentes: a identidade real permanece Loja + identificador.

Requests com chaves diferentes e mesmo Cliente são serializados pelo lock do Cliente. O segundo calcula o saldo depois do consumo do primeiro, impedindo double-spend. A constraint única protege também a persistência; somente sua violação específica é recuperada após rollback do savepoint para comparar o vencedor. Outros `IntegrityError` são propagados. Falha no desconto, no Resgate, em qualquer alocação ou na soma final desfaz integralmente a nova operação.

Resposta ilustrativa, igual para criação `201` e retry `200`:

```json
{
  "id": 42,
  "identificador_externo": "RESGATE-001",
  "loja": {"id": 1, "nome": "Centro"},
  "cliente": {"cpf": "52998224725"},
  "pontos_resgatados": 200,
  "valor_desconto": "10.00",
  "resgatado_em": "2026-09-23T10:35:00-03:00"
}
```

Pontos retornam como inteiro JSON e desconto como string de duas casas. Não são expostos alocações, locks ou credenciais. Não há GET público de saldo, cancelamento, estorno, edição, exclusão ou vínculo obrigatório com Compra nesta fase. Métodos não implementados recebem `405`.

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
| 400 | `pontos_abaixo_do_minimo` | Pontos abaixo do mínimo para Resgate. |
| 400 | `incremento_resgate_invalido` | Pontos incompatíveis com o incremento de Resgate. |
| 400 | `saldo_insuficiente` | Saldo insuficiente para Resgate. |
| 401 | `credencial_invalida` | Credencial de integração inválida. |
| 403 | `acesso_negado` | Acesso negado. |
| 404 | `nao_encontrado` | Recurso não encontrado. |
| 405 | `metodo_nao_permitido` | Método não permitido. |
| 406 | `formato_nao_aceito` | Formato de resposta não aceito. |
| 415 | `formato_nao_suportado` | Formato de conteúdo não suportado. |
| 403 | `loja_fora_do_escopo` | Loja não autorizada para esta integração. |
| 404 | `cliente_nao_encontrado` | Cliente não encontrado. |
| 409 | `idempotencia_conflitante` | Identificador externo já utilizado com dados diferentes. |

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

- `resgate_invalido`;
- `campanha_conflitante`.

Esses códigos futuros ainda não fazem parte do contrato implementado.

## Status HTTP

Semântica HTTP implementada:

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
```

Os endpoints de Cliente e saldo acima são direção de produto, não estão disponíveis e não aparecem no OpenAPI. Cada endpoint deve ganhar critérios de aceite antes da implementação.

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

O schema pode ser obtido como JSON com `Accept: application/vnd.oai.openapi+json`; YAML também está disponível. Ele descreve health, contexto, `POST /api/v1/compras/` e `POST /api/v1/resgates/`, sem endpoints futuros. Compra possui serializers reais de request/response, incluindo `fidelidade` nullable com pontos em strings de quatro casas e expiração. Resgate descreve pontos inteiros, desconto como string decimal, rejeição de campos extras e ausência de backdating. Ambos documentam respostas `201`, `200`, `400`, `401`, `403`, `404`, `409` e `405`.

O security scheme se chama `X-API-Key`, com `type: apiKey`, `in: header` e `name: X-API-Key`. Health não exige autenticação; contexto, Compra e Resgate exigem esse scheme. No Swagger, use **Authorize** e informe a chave completa `<identificador>.<segredo>` para testar os endpoints protegidos. A autorização não é persistida pelo Swagger entre carregamentos. Documentação pública não concede acesso aos dados.

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

Na F3.01, `apps/fidelidade/test_compras.py`, `apps/fidelidade/test_concorrencia_compras.py`, `apps/fidelidade/test_migrations.py` e `apps/api/test_compras.py` cobrem domínio, limites monetários e de identificador, tenancy, retries, conflitos, preservação da origem, concorrência real via conexões independentes, HTTP, OpenAPI e preservação do domínio anterior à migration inicial de Compra. Os testes de concorrência têm PostgreSQL como referência.

Na F3.02, `apps/fidelidade/test_pontos.py`, `apps/fidelidade/test_migration_pontos.py` e `apps/api/test_pontos.py` acrescentam cobertura de cálculo, calendário, limites representáveis, snapshots, imutabilidade, rollback, legado e contrato de fidelidade. Os testes de parâmetros e concorrência existentes foram ampliados para a política corporativa e uma Compra + um Lote.

Na F3.04, `apps/fidelidade/test_resgates.py`, `apps/fidelidade/test_concorrencia_resgates.py`, `apps/fidelidade/test_migration_resgates.py` e `apps/api/test_resgates.py` contêm testes de FEFO, frações, expiração estrita, parâmetros, histórico, Decimal, rollback, autorização, HTTP, OpenAPI e migration. As disputas usam PostgreSQL real com conexões independentes, incluindo idempotência divergente, double-spend e defesa residual por constraint. Esses testes integram a suíte de regressão do projeto.

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
- aplicação de Evento com preservação do histórico.

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
