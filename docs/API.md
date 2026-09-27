# API do Produto

## Objetivo

A API REST é uma interface de primeira classe do DataSystemChallenge. Ela existe para permitir integração com PDVs, ERPs, e-commerces, aplicativos e outros consumidores externos sem duplicar as regras de fidelidade.

A API utiliza Django REST Framework sobre a mesma camada de domínio utilizada pela interface web.

A F2.06 entrega credenciais de integração, health, contexto e OpenAPI. A F3.01 acrescenta registro de Compra e idempotência; a F3.02 acrescenta cálculo base de pontos e LotePontos histórico. A F3.03 acrescenta campanhas temporárias com multiplicador de pontos. A F3.04 acrescenta Resgate idempotente com consumo de Lotes e desconto histórico. A F3.06B acrescenta consulta autenticada do estado atual de fidelidade do Cliente para integrações. A F3.06C acrescenta simulação de Compra sem persistência para o PDV consultar os efeitos atuais de fidelidade antes de finalizar a venda. A F3.06D acrescenta simulação de Resgate sem persistência ou reserva de saldo. A F3.06E acrescenta estorno integral, histórico e idempotente de Resgate. A F3.06F integra Resgate à Compra, expõe máximos utilizáveis e acrescenta limite corporativo sobre o bruto.

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
POST /api/v1/compras/simular/
POST /api/v1/compras/
POST /api/v1/resgates/simular/
POST /api/v1/resgates/estornar/
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
    "valor_monetario_por_ponto": "0.05",
    "possivel": true,
    "maximo_pontos": 700,
    "maximo_desconto": "35.00",
    "limite_resgate_percentual": "100.0000"
  }
}
```

`nivel.pontos_historicos` soma todas as concessões históricas do Cliente, inclusive Lotes expirados ou já consumidos. Portanto, expiração e Resgate não reduzem a classificação de nível.

`saldo.pontos` representa o valor utilizável no instante da consulta: considera somente Lotes ainda não expirados e desconta somente consumo efetivo: alocações sem estorno ou com `devolve_pontos_aplicado=false`.

Quando não existir nível compatível, `nivel.atual` é `null`, mas `nivel.pontos_historicos` continua presente.

Atividade, retorno e aplicabilidade dos benefícios reutilizam a avaliação canônica do domínio. Cliente sem Compra anterior não é considerado retorno. Em caso de inatividade, a política de primeira Compra após inatividade determina se os benefícios de nível seriam aplicáveis naquele instante.

A promoção de retorno só é marcada como aplicável quando o Cliente está efetivamente em retorno e a promoção corporativa está ativa. Caso contrário, seus percentuais retornam zero.

A consulta é somente leitura, usa o instante do servidor, não cria snapshots e não garante o mesmo estado para uma operação posterior. Compra ou Resgate efetivos devem recalcular e revalidar todas as regras.

Loja inexistente ou não autorizada retorna `403 loja_fora_do_escopo`. Cliente inexistente ou pertencente somente a outro tenant retorna `404 cliente_nao_encontrado`, sem revelar informação externa.

A resposta utiliza `Cache-Control: no-store`.

## Simulação de Compra e benefícios — F3.06C

```http
POST /api/v1/compras/simular/
X-API-Key: <identificador>.<segredo>
Content-Type: application/json
```

Entrada:

```json
{
  "loja_id": 1,
  "cliente_cpf": "52998224725",
  "valor": "199.90"
}
```

A simulação usa o instante atual do servidor. Não aceita `ocorrida_em`, identificador externo, pontos, percentuais, multiplicadores ou descontos calculados pelo PDV.

`valor` segue o mesmo contrato monetário da Compra real: string decimal positiva, com até duas casas, entre `0.01` e `9999999999.99`. Float não é aceito.

Exemplo de resposta:

```json
{
  "cliente": {
    "cpf": "52998224725",
    "nome": "Ana Silva"
  },
  "simulada_em": "2026-09-26T13:00:00-03:00",
  "atividade": {
    "ativo": true,
    "retorno": false,
    "ultima_compra_em": "2026-09-20T10:00:00-03:00"
  },
  "nivel": {
    "atual": {
      "nome": "Prata",
      "pontos_minimos": "1000.0000"
    },
    "bonus_pontos": {
      "nome": "Prata",
      "pontos_minimos": "1000.0000"
    },
    "beneficios_aplicaveis": true,
    "bonus_pontos_percentual": "10.0000",
    "desconto_percentual": "5.0000"
  },
  "campanha": {
    "aplicavel": true,
    "nome": "Semana do Cliente",
    "multiplicador_pontos": "2.0000"
  },
  "promocao_retorno": {
    "aplicavel": false,
    "bonus_pontos_percentual": "0.0000",
    "desconto_percentual": "0.0000"
  },
  "valores": {
    "bruto": "199.90",
    "desconto_total": "9.99",
    "final": "189.91",
    "elegivel_pontos": "199.90"
  },
  "pontos": {
    "base": "199.9000",
    "apos_campanha": "399.8000",
    "bonus_nivel": "19.9900",
    "bonus_retorno": "0.0000",
    "total_estimado": "419.7900"
  }
}
```

`nivel.atual` representa o nível determinado pelo progresso histórico anterior à Compra simulada.

`nivel.bonus_pontos` representa o nível efetivamente usado para o bônus de pontos. Ele pode divergir de `nivel.atual` quando a política utiliza `ATINGIDO_NA_COMPRA`.

`nivel.beneficios_aplicaveis` informa se os benefícios de nível podem ser usados naquele instante. Os percentuais configurados continuam visíveis mesmo quando estão suspensos por inatividade; nesse caso, os componentes efetivamente calculados refletem a suspensão.

Sem campanha aplicável, `campanha.aplicavel` é `false`, `nome` é `null` e `multiplicador_pontos` é `1.0000`.

`valores.elegivel_pontos` informa qual valor efetivamente serviu de base monetária para geração de pontos após a política `BRUTO` ou `LIQUIDO`.

Os componentes de pontos são apresentados separadamente:

- `base`: pontos antes de campanha e bônus;
- `apos_campanha`: pontos depois do multiplicador da campanha;
- `bonus_nivel`: componente adicional do nível;
- `bonus_retorno`: componente adicional da promoção de retorno;
- `total_estimado`: concessão estimada para a Compra.

A simulação reutiliza a mesma avaliação de domínio da Compra efetiva para atividade, retorno, nível, descontos e pontos. A seleção de campanha também segue as mesmas regras de Empresa, Loja e período.

A operação não cria `Compra`, `LotePontos`, aplicação de campanha, Resgate ou snapshot, não consome saldo e não altera atividade persistida.

O resultado não constitui reserva. Configuração, campanha, nível e demais condições são recalculados quando a Compra efetiva for registrada.

Loja inexistente ou fora do escopo retorna `403 loja_fora_do_escopo`. Cliente inexistente ou pertencente somente a outro tenant retorna `404 cliente_nao_encontrado`.

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

Os campos abaixo são obrigatórios, exceto o identificador de Resgate:

| Campo | Contrato |
| --- | --- |
| `loja_id` | ID positivo de Loja autorizada pela credencial. Loja externa, não autorizada ou inexistente recebe `403 loja_fora_do_escopo`. |
| `identificador_externo` | String de até 255 caracteres após `strip()` nas extremidades; não pode ficar vazia. Preserva case, espaços e conteúdo interno. |
| `cliente_cpf` | CPF normalizado/validado pela regra existente. Resolve a identidade global e o Cliente da Empresa da Loja. Não cria vínculo nem altera Usuario. Sem Cliente no tenant: `404 cliente_nao_encontrado`. |
| `valor` | Decimal positivo com até duas casas decimais: `0.01` a `9999999999.99`. Envie string decimal, nunca float. Não há arredondamento de valores com casas excedentes. |
| `resgate_identificador_externo` | Opcional; string não vazia de até 255 caracteres após strip. Referencia Resgate histórico da mesma Loja, Cliente e tenant, não estornado e ainda não vinculado. |
| `ocorrida_em` | ISO 8601 com timezone explícito. Data sem timezone é inválida. Sem limites de passado/futuro nesta fase. |

O domínio `apps.fidelidade` persiste `Compra` com Loja, Cliente, credencial de origem, identificador externo, valor, instante da venda e `criada_em` preenchido pelo servidor. Os relacionamentos usam `PROTECT`. Model e service validam coerência de tenant; a autorização reutiliza os helpers da F2.06. Para novas operações, o service cria também um LotePontos histórico, na mesma transação.

A chave idempotente é **Loja + identificador_externo**, protegida por `UniqueConstraint` no PostgreSQL. O mesmo identificador pode existir em outra Loja. O valor usa `DecimalField(max_digits=12, decimal_places=2)` e possui constraint `valor > 0`.

| Situação | Resultado |
| --- | --- |
| Primeira chamada válida | Cria Compra + LotePontos atomicamente e retorna `201 Created`. |
| Mesma chave com Loja, Cliente, valor, instante e Resgate equivalentes | Retorna Compra e fidelidade originais, sem recálculo, com `200 OK`. Legado sem Lote retorna `fidelidade: null`. |
| Mesma chave com Cliente, valor, instante ou Resgate divergentes | Retorna `409 idempotencia_conflitante`, sem alterar ou duplicar Compra ou Lote. |

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

Além desses campos, a F3.06F retorna `resgate` e `resumo`, descritos abaixo. Valores monetários são strings com duas casas. O bloco `fidelidade` expõe apenas pontos base, pontos concedidos (strings decimais com exatamente quatro casas) e expiração. Não retorna segredo, hash, senha, credencial completa ou os demais snapshots internos. Nesta fase não há GET/listagem, edição, cancelamento, estorno ou exclusão de Compra pela API.

## Compra com Resgate e limites — F3.06F

`Compra.valor` permanece bruto. Para usar um Resgate, envie `resgate_identificador_externo`
no registro da Compra. Seu `valor_desconto` é lido exclusivamente do histórico;
qualquer campo não declarado é rejeitado com `400 requisicao_invalida`, inclusive
`valor_desconto`, `pontos_concedidos`, `saldo`, `nivel` e percentuais de desconto.
`resgate_identificador_externo` é o único novo campo opcional. Há no máximo um Resgate
por Compra e uma Compra por Resgate. Não há comparação entre `resgatado_em` e `ocorrida_em`.

A política corporativa `limite_resgate_percentual` aceita Decimal de `0.0000` a
`100.0000`, padrão `100.0000`, sem override por Loja. FATECalçados usa `50.0000`.
O teto é `valor bruto × percentual / 100`, truncado em centavos para nunca exceder
o limite, independentemente da ordem dos descontos percentuais. Zero desabilita
utilização. O máximo aplicável é `min(teto contratual, capacidade efetiva)`: a
capacidade é o bruto em ANTES, ou o restante após descontos percentuais em DEPOIS,
sem arredondar a capacidade para cima. Com bruto 100, limite 50%, taxa 0,05 e
desconto 70%, ANTES permite R$ 50/1.000 pontos e DEPOIS R$ 30/600 pontos.
A conversão continua `pontos × valor_monetario_por_ponto`.

`resgate.maximo_pontos` e `resgate.maximo_desconto` na consulta de fidelidade informam
o saldo utilizável na sequência `mínimo + N × incremento` e seu equivalente monetário.
`possivel` indica disponibilidade; `limite_resgate_percentual` informa a restrição
que será aplicada a uma Compra. Sem valor de Compra, não há teto financeiro para
calcular na consulta; limite zero retorna máximo zero.

A simulação de Compra acrescenta `saldo.pontos` e `resgate`:

```json
{
  "saldo": {"pontos": "1099.9900"},
  "resgate": {
    "possivel": true,
    "limite_resgate_percentual": "50.0000",
    "maximo_pontos": 1000,
    "maximo_desconto": "50.00"
  }
}
```

Exemplo para Compra bruta de R$ 101,99, mínimo 100, incremento 50 e taxa R$ 0,05.
O teto financeiro é R$ 50,99; o máximo efetivamente conversível é R$ 50,00.
O backend considera saldo, mínimo, incremento, taxa e máximo aplicável; o PDV não precisa
reproduzir esse cálculo. A simulação continua mostrando benefícios sem Resgate
aplicado em `valores` e `pontos`; o bloco `resgate` informa a possibilidade de uso,
sem consumir, reservar ou aplicar automaticamente o máximo.

Um Resgate já emitido não é reduzido: se seu desconto histórico exceder o máximo aplicável à
Compra, o vínculo é rejeitado. Pontos e taxa do Resgate não são recalculados pela
configuração atual. O desconto histórico entra no mesmo avaliador canônico da
simulação, respeitando ANTES/DEPOIS, BRUTO/LIQUIDO, nível, retorno e campanha.
BRUTO usa `max(0, bruto − desconto_resgate)`: ignora percentuais, mas nunca gera
pontos sobre a parcela paga por Resgate. LIQUIDO usa o final após todos os descontos.
Para bruto 100, Resgate 50 e percentual 20%, ANTES produz final/base LIQUIDO 40,
DEPOIS produz 30, e a base BRUTO é 50 em ambas as ordens.

Erros específicos do registro de Compra:

| Condição | Resultado |
| --- | --- |
| Resgate não encontrado para a Loja e Cliente autorizados, inclusive outro tenant | `404 resgate_nao_encontrado` |
| Resgate estornado | `409 resgate_ja_estornado` |
| Resgate usado por outra Compra | `409 resgate_vinculado_compra` |
| Desconto histórico acima do máximo aplicável à Compra | `400 limite_resgate_excedido` |
| Retry altera, acrescenta ou remove o Resgate original | `409 idempotencia_conflitante` |

Retry equivalente retorna o vínculo e os valores históricos antes de revalidar
configuração atual. Uma Compra concluída bloqueia o estorno isolado do Resgate
(`409 resgate_vinculado_compra`). Cancelamento/estorno de Compra está fora do escopo.

A resposta mantém todos os campos anteriores e acrescenta:

- `resgate`: `null` ou `{identificador_externo, pontos_resgatados, valor_desconto}`;
- `resumo.valores`: `bruto`, `desconto_total`, `final`, `elegivel_pontos`;
- `resumo.pontos`: `base`, `apos_campanha`, `bonus_nivel`, `bonus_retorno`, `total` (quatro casas);
- `resumo.beneficios`: nomes de nível para desconto/bônus, aplicabilidade do nível,
  retorno, percentuais aplicados de nível/retorno, multiplicador de campanha,
  ordem do Resgate e base de pontos.

`resumo` é `null` para legado sem snapshot de benefícios. Snapshot v1 continua
legível; novos snapshots v2 incluem o desconto de Resgate e o limite aplicado.
Não há recálculo com a política atual nem exposição de snapshot, alocações ou locks.

## Motor de pontos e histórico — F3.02

O PDV envia fatos da venda; pontos enviados no payload não definem a concessão. A plataforma resolve `pontos_por_real` pelo padrão do produto → Empresa → override permitido da Loja.

Dois parâmetros são configuráveis **somente por Empresa**, na tela administrativa já existente, por Administrador ativo:

| Parâmetro | Valores | Default |
| --- | --- | --- |
| `precisao_pontos` | `0`, `1`, `2`, `4` | `2` |
| `modo_arredondamento_pontos` | `HALF_UP`, `DOWN`, `UP` | `HALF_UP` |

A Loja continua podendo sobrescrever apenas `pontos_por_real`. Models e constraints rejeitam políticas fora dos conjuntos permitidos.

```text
pontos_base = valor_elegivel_pontos × pontos_por_real efetivo
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
valor_elegivel_pontos × pontos_por_real = pontos_base (pré-campanha)
pontos_base × multiplicador = resultado exato intermediário
política corporativa aplicada uma vez = pontos_concedidos
```

Exemplo: `49.90 × 1.25 = 62.3750` base; Evento `2.0000x`; precisão 2 e HALF_UP → `124.7500` concedidos. O bloco público continua contendo somente `pontos_base`, `pontos_concedidos` e `expira_em`; o resumo público da F3.06F também informa o multiplicador histórico, sem expor o snapshot interno.

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

## Simulação de Resgate — F3.06D

```http
POST /api/v1/resgates/simular/
X-API-Key: <identificador>.<segredo>
Content-Type: application/json
```

Entrada estrita, com exatamente os três campos obrigatórios:

```json
{
  "loja_id": 1,
  "cliente_cpf": "52998224725",
  "pontos": 100
}
```

`loja_id` deve ser inteiro positivo, seguindo a validação existente da API. O CPF segue a validação existente, inclusive normalização da máscara. `pontos` usa o mesmo contrato físico do Resgate real: inteiro JSON entre 1 e 99999999999999999999, sem float, string ou booleano. Campos extras são rejeitados, inclusive `identificador_externo`, `resgatado_em`, `ocorrida_em`, `valor_desconto`, `valor_monetario_por_ponto`, `saldo` e qualquer backdating ou valor calculado pelo consumidor.

Sucesso: HTTP 200, com `Cache-Control: no-store`.

```json
{
  "cliente": {
    "cpf": "52998224725",
    "nome": "Ana Silva"
  },
  "simulada_em": "2026-09-26T15:00:00-03:00",
  "pontos_resgatados": 100,
  "valor_desconto": "5.00",
  "saldo": {
    "atual": "250.0000",
    "projetado": "150.0000"
  }
}
```

O servidor fixa um único instante para a simulação e resolve a configuração efetiva Empresa/Loja. Exige `pontos >= resgate_minimo_pontos` e exatamente `(pontos - resgate_minimo_pontos) % incremento_resgate_pontos == 0`. O desconto é calculado autoritativamente pelo backend com o mesmo cálculo do Resgate real: pontos multiplicados pela taxa efetiva, limites financeiros existentes e arredondamento HALF_UP em centavos.

`saldo.atual` soma as concessões dos Lotes do Cliente com `expira_em > simulada_em`, descontando as alocações já persistidas nesses Lotes. Lotes expirados no próprio instante não contam; Lotes persistidos com aquisição futura continuam contando se ainda válidos, conforme a semântica do Resgate real. `saldo.projetado` é o saldo atual menos os pontos solicitados. Ambos são strings com quatro casas decimais; pontos resgatados são inteiro JSON. Histórico com consumo acima da concessão é uma inconsistência de histórico, distinta de saldo insuficiente.

A operação apenas lê o estado momentâneo: não cria Resgate, AlocacaoResgate ou snapshot, não consome Lotes, não usa idempotência, não toma locks de Resgate e não reserva saldo. Alterações concorrentes podem tornar a projeção obsoleta. O Resgate real obrigatoriamente recalcula e revalida saldo, configuração e desconto, mantendo sua atomicidade e seus locks.

A autorização segue o Resgate real: escopo EMPRESA ou LOJAS. Loja inexistente ou fora do escopo retorna a mesma resposta 403, sem revelar existência. Cliente inexistente ou vinculado apenas a outro tenant retorna 404. A resposta não expõe Lotes, alocações nem outros detalhes internos.

| HTTP | Código |
| --- | --- |
| 400 | `requisicao_invalida`, `pontos_abaixo_do_minimo`, `incremento_resgate_invalido` ou `saldo_insuficiente` |
| 401 | `credencial_invalida` |
| 403 | `loja_fora_do_escopo` |
| 404 | `cliente_nao_encontrado` |
| 405 | `metodo_nao_permitido` |

Somente POST e OPTIONS são aceitos; GET, PUT, PATCH e DELETE retornam 405. O OpenAPI documenta o POST, autenticação e todas essas respostas.

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
        - soma do consumo efetivo das AlocacaoResgate desses Lotes
```

Em `expira_em == T`, o Lote já está expirado. A elegibilidade usa a expiração persistida, inclusive para Lotes cuja Compra possui data futura; não acrescenta um filtro por aquisição. O consumo usa `pontos_concedidos`, que já incorpora a campanha aplicada, sem recalcular campanha nem usar `pontos_base`.

FEFO é determinístico: `expira_em ASC → adquiridos_em ASC → pk ASC`. Lotes permanecem imutáveis; somente alocações registram consumo. Um Resgate de 100 pode consumir `99.7500` do Lote A e `0.2500` do Lote B. O consumo efetivo acumulado nunca pode exceder a concessão de cada Lote, e a soma das alocações deve ser exatamente o Resgate.

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

Pontos retornam como inteiro JSON e desconto como string de duas casas. Não são expostos alocações, locks ou credenciais. A consulta de fidelidade informa o saldo atual; o estorno integral está documentado abaixo. Não há edição, exclusão ou vínculo obrigatório com Compra nesta fase. Métodos não implementados recebem `405`.

## Estorno de Resgate — F3.06E

```text
POST /api/v1/resgates/estornar/
X-API-Key: <identificador>.<segredo>
```

O estorno é sempre integral. Entrada estrita, somente:

```json
{
  "loja_id": 1,
  "resgate_identificador_externo": "RESGATE-001",
  "identificador_externo": "ESTORNO-001"
}
```

Os identificadores são strings não vazias após `strip` externo, até 255 caracteres; case e conteúdo interno são preservados. Campos extras são rejeitados, inclusive CPF, pontos, desconto, saldo, snapshots e datas. Não existe backdating; `estornado_em` é capturado uma única vez pelo servidor após o lock do Cliente. Somente POST e OPTIONS são permitidos.

Resposta de criação **201** ou retry equivalente **200**, com `Cache-Control: no-store`:

```json
{
  "identificador_externo": "ESTORNO-001",
  "resgate_identificador_externo": "RESGATE-001",
  "loja": {"id": 1, "nome": "Centro"},
  "cliente": {"cpf": "52998224725"},
  "pontos_estornados": 200,
  "valor_desconto_original": "10.00",
  "devolve_pontos_aplicado": true,
  "estornado_em": "2026-09-26T16:00:00-03:00"
}
```

`pontos_estornados` é inteiro JSON e representa a quantidade integral do Resgate original, não necessariamente a quantidade que voltou ao saldo. `valor_desconto_original` é string decimal com duas casas. Ambos são derivados do Resgate imutável. Não são expostos IDs internos de Estorno, Resgate, Lote ou Alocação.

A Empresa configura `devolver_pontos_ao_estornar_resgate` no formulário de configuração de fidelidade, grupo Resgate. O default é **true**, inclusive para configurações existentes na migration. Não existe override por Loja. O valor efetivo no instante da operação é preservado em `EstornoResgate.devolve_pontos_aplicado`:

- **false**: registra o estorno, mas as alocações continuam consumindo pontos; nada é devolvido.
- **true**: as alocações deixam de consumir capacidade dos Lotes originais; somente pontos de Lotes ainda válidos (`expira_em > instante`) ficam disponíveis.

Pontos expirados nunca voltam. Nenhuma validade é renovada, `expira_em` nunca é alterado, nenhum Lote expirado é reativado e nenhum Lote compensatório/substituto é criado. Resgate e AlocacaoResgate originais não mudam. Não se persiste crédito ou “pontos restaurados”. Um consumo de 80 pontos ainda válidos + 20 expirados libera apenas 80 com snapshot true e zero com false. Consulta, simulação, novo Resgate e validação de capacidade aplicam a mesma regra canônica de consumo efetivo. Retry do Resgate original continua retornando o histórico, sem consumir novamente.

| Situação | HTTP / código público |
| --- | --- |
| Novo estorno integral | `201` |
| Resgate vinculado a Compra | `409 resgate_vinculado_compra` |
| Mesma Loja, chave de estorno e Resgate original | `200`, mesmo fato e snapshot |
| Payload inválido ou campos extras | `400 requisicao_invalida` |
| Credencial ausente, inválida ou desativada | `401 credencial_invalida` |
| Loja inexistente ou fora do escopo EMPRESA/LOJAS | `403 loja_fora_do_escopo` |
| Resgate ausente na Loja autorizada, inclusive chave de outra Loja/tenant | `404 resgate_nao_encontrado` |
| Chave de estorno usada para outro Resgate | `409 idempotencia_conflitante` |
| Resgate já estornado com outra chave | `409 resgate_ja_estornado` |
| GET, PUT, PATCH, DELETE ou outro método não permitido | `405 metodo_nao_permitido` |

Retry equivalente retorna antes de resolver configuração atual; mudanças posteriores no parâmetro nunca alteram estornos anteriores. A credencial registrada é a da primeira operação, mesmo quando o retry usa outra credencial autorizada.

A transação arbitra a chave pelo advisory lock no namespace próprio `estorno-resgate:<loja_id>:<identificador>` (SHA-256, primeiros oito bytes signed de 64 bits), antes de localizar o Resgate na Loja autorizada. O lock `select_for_update(no_key=True)` no mesmo Cliente usado pelo Resgate serializa novas operações. Após esse lock, verifica novamente a ausência de estorno e de vínculo com Compra, resolve a configuração e cria o fato. A unicidade SQL garante um estorno por Resgate e uma chave por Loja. Não existe estorno parcial nem reversão do estorno.

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
| 404 | `resgate_nao_encontrado` | Resgate não encontrado. |
| 409 | `resgate_ja_estornado` | Resgate já estornado. |
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

O schema pode ser obtido como JSON com `Accept: application/vnd.oai.openapi+json`; YAML também está disponível. Ele descreve health, contexto, consulta de fidelidade, simulações de Compra e Resgate, `POST /api/v1/compras/` e `POST /api/v1/resgates/`, sem endpoints futuros. A simulação de Resgate documenta entrada estrita e respostas `200`, `400`, `401`, `403`, `404` e `405`. Compra possui serializers reais de request/response, incluindo `fidelidade` nullable com pontos em strings de quatro casas e expiração. Resgate descreve pontos inteiros, desconto como string decimal, rejeição de campos extras e ausência de backdating. Ambos documentam respostas `201`, `200`, `400`, `401`, `403`, `404`, `409` e `405`.

O security scheme se chama `X-API-Key`, com `type: apiKey`, `in: header` e `name: X-API-Key`. Health não exige autenticação; contexto, consulta de fidelidade, simulações, Compra e Resgate exigem esse scheme. No Swagger, use **Authorize** e informe a chave completa `<identificador>.<segredo>` para testar os endpoints protegidos. A autorização não é persistida pelo Swagger entre carregamentos. Documentação pública não concede acesso aos dados.

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
