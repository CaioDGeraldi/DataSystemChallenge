# Integração por API — Retorna

## Papel da API

A API da Retorna é a fronteira entre sistemas externos e o domínio de fidelidade.

Ela existe para que um PDV, ERP, e-commerce, aplicativo ou terminal de Loja consiga informar fatos da operação e receber o resultado calculado pela Retorna sem duplicar regras de negócio fora da plataforma.

```text
PDV / ERP / e-commerce
          ↓
       API Retorna
          ↓
 autenticação + escopo
          ↓
 domínio de fidelidade
          ↓
      PostgreSQL
          ↓
 resposta ao sistema externo
```

A API **não substitui** o PDV ou o ERP. Venda, pagamento, estoque, fiscal e caixa continuam pertencendo aos sistemas responsáveis por essas funções.

A Retorna recebe somente os dados necessários ao programa de fidelidade e aplica as políticas definidas pela Empresa.

## Princípio principal

> Sistemas externos enviam fatos. A Retorna decide o resultado de fidelidade.

Um PDV pode informar:

- qual Loja realizou a venda;
- qual Cliente realizou a compra;
- qual é o identificador externo da operação;
- valor da compra;
- quando ela ocorreu.

O PDV não deve ser fonte de verdade para:

- pontos concedidos;
- nível do Cliente;
- benefício calculado;
- validade dos pontos;
- campanha aplicada;
- desconto de fidelidade derivado das regras do programa.

Esses resultados pertencem ao domínio da Retorna.

## Responsabilidades implementadas atualmente

O contrato real deve continuar sendo consultado em `docs/API.md` e no OpenAPI. Na base integrada até a F3.01, a API já possui estas responsabilidades:

### 1. Verificar disponibilidade básica

```text
GET /api/v1/health/
```

Serve para verificar se a aplicação está respondendo.

### 2. Autenticar integrações

Integrações utilizam credenciais próprias por `X-API-Key`, separadas das contas humanas.

A API valida:

- credencial;
- Empresa da integração;
- escopo `EMPRESA` ou `LOJAS`;
- Loja que pode receber a operação.

### 3. Expor o contexto autorizado

```text
GET /api/v1/contexto/
```

Permite que uma integração autenticada saiba em qual Empresa e em quais Lojas sua credencial pode operar.

### 4. Registrar Compras

```text
POST /api/v1/compras/
```

O consumidor envia os fatos da venda. A Retorna valida Cliente, Empresa, Loja, valor, instante e escopo antes de persistir a Compra.

### 5. Garantir idempotência

A mesma venda pode ser reenviada após falha de conexão sem gerar uma segunda Compra quando os fatos forem equivalentes.

A chave atual é:

```text
Loja + identificador_externo
```

Isso é importante porque uma integração real não pode depender de saber se a resposta da primeira tentativa chegou ao PDV.

### 6. Fornecer contrato versionado e documentado

A API usa `/api/v1/` e OpenAPI/Swagger/ReDoc.

Mudanças incompatíveis de contrato não devem acontecer silenciosamente.

## Responsabilidades da vertical planejada

Os itens abaixo representam a direção do produto e só viram contrato real depois da respectiva fase ser implementada, testada e integrada na `main`.

### Resultado da fidelidade na própria Compra

Com o motor de pontos, a ideia é que o PDV envie a Compra e receba o resultado calculado pela Retorna.

Direção:

```text
PDV envia Compra
↓
Retorna resolve configuração
↓
Retorna calcula fidelidade
↓
Retorna persiste Compra + histórico
↓
API devolve o resultado
```

Exemplo conceitual:

```json
{
  "id": 123,
  "valor": "49.90",
  "fidelidade": {
    "pontos_base": "62.3750",
    "pontos_concedidos": "62.3800",
    "expira_em": "2027-09-23T14:30:00-03:00"
  }
}
```

O consumidor recebe o resultado; ele não escolhe `62.3800` arbitrariamente.

### Consulta de Cliente e saldo

Para um fluxo de atendimento no PDV, poderá ser necessário consultar informações do Cliente antes de um resgate.

Direções já registradas no produto incluem endpoints equivalentes a:

```text
GET /api/v1/clientes/por-cpf/{cpf}/
GET /api/v1/clientes/{id}/saldo/
```

Eles ainda precisam de critérios de aceite antes de implementação.

O objetivo é permitir perguntas como:

- esse Cliente participa do programa desta Empresa?
- qual saldo utilizável ele possui?
- existem pontos próximos de expirar?
- qual informação mínima deve ser mostrada ao operador?

A API deve expor somente dados necessários e respeitar minimização de dados pessoais.

### Resgate

Quando o domínio de Resgate existir, a integração deverá permitir que o sistema de venda solicite um resgate sem calcular localmente o benefício.

Direção conceitual:

```text
PDV informa Cliente + Loja + intenção de resgate
↓
Retorna valida saldo e regras
↓
Retorna calcula valor elegível
↓
Retorna registra o histórico
↓
API devolve o resultado ao PDV
```

Endpoint já apontado como direção de produto:

```text
POST /api/v1/resgates/
```

O contrato só deve ser fechado quando a fase de Resgate for especificada.

### Configuração efetiva para transparência

Pode existir futuramente leitura da configuração efetiva de uma Loja, por exemplo:

```text
GET /api/v1/lojas/{id}/configuracao-efetiva/
```

Esse endpoint serviria para transparência e integração, mas **não** para o PDV copiar o motor da Retorna e recalcular fidelidade localmente.

## O que a API não precisa fazer

A API não deve virar um CRUD público de todos os models.

Não é objetivo:

- expor tabelas internas apenas porque existem;
- permitir alteração arbitrária do histórico;
- permitir que o PDV envie pontos como fonte de verdade;
- replicar o motor de fidelidade no consumidor;
- substituir o ERP;
- controlar estoque;
- emitir nota fiscal;
- processar pagamento;
- controlar caixa;
- expor segredos ou relações técnicas internas;
- oferecer endpoints administrativos sem caso de uso real.

## Por que isso importa para o produto

Sem API, a Retorna seria principalmente uma aplicação isolada e exigiria cadastro manual de cada venda ou integração específica feita dentro de cada sistema parceiro.

Com uma API estável:

```text
Sistema A ─┐
Sistema B ─┼── API Retorna ── domínio único de fidelidade
Sistema C ─┘
```

Todos os consumidores usam o mesmo contrato e o mesmo motor de regras.

Isso permite que a Retorna seja apresentada como **produto integrável**, não apenas como um dashboard.

## Como explicar na banca

Versão curta para Gestão:

> A Retorna não precisa substituir o sistema que a loja já usa. O PDV ou ERP envia a venda para a nossa API, e a Retorna aplica as regras de fidelidade e devolve o resultado.

Complemento técnico:

> Cada integração possui uma credencial com escopo de Empresa ou Loja, o contrato é versionado, os retries de Compra são idempotentes e a documentação é publicada em OpenAPI.

## Exemplo ponta a ponta esperado

A vertical final deve caminhar para:

```text
1. Empresa configura seu programa
2. Loja herda/aplica os parâmetros permitidos
3. PDV realiza a venda
4. PDV envia a Compra à API
5. Retorna autentica e valida o escopo
6. Retorna calcula e registra fidelidade
7. API devolve o resultado ao PDV
8. Cliente pode acumular/resgatar conforme as regras
9. Dashboard transforma as operações em indicadores de Gestão
```

Cada passo só pode ser descrito como implementado quando a fase correspondente estiver integrada.