# Arquitetura do Produto

## Visão

O DataSystemChallenge é uma plataforma de fidelidade independente e multiempresa. A FATECalçados é tratada como uma configuração e conjunto de dados de demonstração, não como um caso especial codificado no produto.

A aplicação deve permitir que novas Empresas sejam cadastradas sem alteração de código, cada uma com `1..N` Lojas, políticas próprias de fidelidade e exceções por unidade quando permitido.

## Princípios

1. `Empresa` é o tenant principal do produto.
2. Uma Empresa possui `1..N` Lojas; a quantidade de lojas nunca é hardcoded.
3. Políticas de negócio que podem variar entre Empresas são configuráveis.
4. Lojas herdam por padrão as configurações da Empresa e armazenam apenas overrides.
5. Eventos e campanhas modificam regras temporariamente sem alterar a configuração base.
6. Papel define **o que** uma pessoa pode fazer; escopo define **onde** ela pode fazer.
7. Dados de uma Empresa não podem ser acessados por membros ou integrações de outra Empresa.
8. Invariantes técnicas, estruturais e de segurança permanecem no código e não viram parâmetros.
9. Operações históricas guardam o resultado efetivamente aplicado no momento em que ocorreram.
10. A API é uma interface de primeira classe do produto e utiliza a mesma camada de domínio da interface web.

## Multiempresa

A estrutura conceitual é:

```text
Plataforma
├── Empresa A
│   ├── Loja A1
│   ├── Loja A2
│   └── Loja A3
├── Empresa B
│   └── Loja B1
└── Empresa C
    ├── Loja C1
    └── Loja C2
```

O MVP pode utilizar um único PostgreSQL com isolamento lógico por Empresa. Entidades de negócio devem permitir determinar a Empresa à qual pertencem, direta ou indiretamente.

Exemplos:

```text
Loja -> Empresa
Cliente -> Empresa
MembroEmpresa -> Empresa
Compra -> Loja -> Empresa
LotePontos -> Cliente -> Empresa
Resgate -> Cliente -> Empresa
Evento -> Empresa
```

Consultas e autorizações devem respeitar esse escopo. Alterar uma URL ou identificador não pode permitir acesso cross-tenant.

## Parâmetros

### Definição

Parâmetro é uma configuração de negócio tipada e validada cujo valor pode variar entre Empresas e, quando permitido, entre Lojas, alterando o comportamento do produto sem exigir alteração ou novo deploy de código.

Exemplos de parâmetros:

- pontos por real;
- validade dos pontos;
- pontos mínimos para resgate;
- incremento de resgate;
- conversão de pontos em desconto;
- período utilizado para considerar um cliente ativo;
- regras de pontuação mínima;
- parâmetros de níveis de fidelidade.

### O que não é parâmetro

Não devem ser parametrizadas invariantes como:

- CPF precisa ser válido e normalizado;
- CNPJ precisa ser válido e normalizado;
- senha deve ser armazenada com hash;
- Loja pertence a uma Empresa;
- Compra pertence a uma Loja;
- isolamento entre Empresas;
- constraints necessárias para integridade.

A regra é:

> Políticas de negócio que podem variar entre Empresas são configuráveis; invariantes estruturais, técnicas e de segurança permanecem no domínio.

## Configuração hierárquica

A resolução de configuração segue esta precedência:

```text
Padrão do produto
        ↓
Configuração da Empresa
        ↓
Override da Loja
        ↓
Evento/Campanha vigente
```

Uma Loja não recebe uma cópia de todas as configurações da Empresa. Ela armazena somente valores que explicitamente sobrescreve.

Exemplo:

```text
Empresa
- pontos_por_real = 1
- validade_meses = 12

Loja Araras
- sem overrides

Loja Limeira
- pontos_por_real = 2
```

Resultado efetivo:

```text
Araras
- pontos_por_real = 1        <- Empresa
- validade_meses = 12       <- Empresa

Limeira
- pontos_por_real = 2       <- Loja
- validade_meses = 12       <- Empresa
```

Se a Empresa alterar `validade_meses`, todas as Lojas que estiverem herdando recebem a nova configuração automaticamente. Overrides permanecem intactos.

Nem todo parâmetro precisa permitir override por Loja. A definição de cada parâmetro deve informar em quais escopos ele pode variar.

## Tipagem e validação de parâmetros

Parâmetros não devem ser tratados como um dicionário irrestrito de strings. Cada definição deve possuir semântica conhecida, tipo e validação.

Exemplos:

```text
pontos_por_real
- tipo: Decimal
- valor mínimo: 0
- configurável por Empresa: sim
- configurável por Loja: sim

validade_pontos_meses
- tipo: Integer
- valor mínimo: 1
- configurável por Empresa: sim
- configurável por Loja: conforme regra do produto
```

Uma possível modelagem futura é:

```text
DefinicaoParametro
├── codigo
├── nome
├── descricao
├── tipo
├── grupo
├── permite_empresa
├── permite_loja
└── regras de validacao

ConfiguracaoEmpresa
├── empresa
├── parametro
└── valor

ConfiguracaoLoja
├── loja
├── parametro
└── valor
```

A implementação concreta será definida em Issue própria antes do código.

## Níveis de fidelidade

Bronze, Prata e Ouro não devem ser tratados como estruturas obrigatórias do produto. Eles representam a configuração atual do caso de demonstração.

A direção desejada é permitir níveis configuráveis por Empresa, por exemplo:

```text
Empresa A
- Bronze
- Prata
- Ouro

Empresa B
- Standard
- VIP

Empresa C
- Bronze
- Prata
- Ouro
- Diamond
```

Faixas, ordem e benefícios devem pertencer ao domínio configurável, respeitando as capacidades suportadas pelo motor de fidelidade.

## Eventos e campanhas

Eventos são modificadores temporários das regras normais de fidelidade.

Exemplo:

```text
Configuração base da Loja
- 1.5 ponto por real

Black Friday
- período: 29/11 00:00 até 29/11 23:59
- multiplicador: 2x

Resultado efetivo durante o evento
- 3 pontos por real
```

O evento não altera `pontos_por_real` permanentemente. Ao terminar, a configuração base volta a ser a única aplicável.

Eventos podem possuir escopo:

- Empresa inteira;
- conjunto específico de Lojas;
- uma única Loja.

Para o MVP, o primeiro tipo de campanha a priorizar é multiplicador de pontos por período e escopo de Lojas.

Conflitos entre campanhas precisam de política explícita. A direção inicial é não permitir campanhas conflitantes sobre a mesma regra, Loja e intervalo até existir uma política de prioridade/composição definida.

### Histórico

Uma transação histórica não deve ser recalculada quando parâmetros ou campanhas mudarem. Compra e operações de fidelidade devem armazenar o resultado aplicado, como pontos concedidos e informações suficientes para auditoria.

## Pessoas, papéis e escopos

Identidade continua separada dos papéis de negócio.

```text
Usuario
= identidade e autenticação
```

Para o produto multiempresa, a direção arquitetural é evoluir o perfil de Gestor para um vínculo de membro da Empresa.

```text
MembroEmpresa
├── usuario
├── empresa
├── papel
├── ativo
└── criado_em
```

Papéis iniciais:

- `Administrador da Empresa`;
- `Gestor de Loja`.

### Administrador da Empresa

O primeiro usuário responsável pelo onboarding cria a Empresa e se torna seu Administrador.

O Administrador possui escopo corporativo e acesso a todas as Lojas atuais e futuras daquela Empresa. Não é necessário criar uma associação de acesso para cada Loja.

Responsabilidades possíveis:

- administrar dados da Empresa;
- criar Lojas;
- configurar padrões corporativos;
- administrar overrides quando permitido;
- convidar membros;
- atribuir Lojas aos Gestores;
- criar eventos corporativos ou locais;
- visualizar indicadores consolidados.

### Gestor de Loja

O Gestor possui acesso somente às Lojas explicitamente atribuídas. Um Gestor pode possuir `1..N` Lojas.

```text
MembroEmpresa
     ↓
AcessoLoja
├── Loja Araras
└── Loja Limeira
```

Um Gestor de Araras não pode acessar Campinas apenas alterando a URL ou identificador. A autorização deve ser aplicada no backend.

### Papel e escopo

São conceitos diferentes:

```text
Papel
= o que a pessoa pode fazer

Escopo
= em quais recursos ela pode fazer
```

Não devem existir papéis específicos por Loja, como `GESTOR_ARARAS`. A Loja pertence ao escopo de acesso, não ao nome do papel.

## Fluxo de onboarding

```text
1. Usuario cria conta
2. cria Empresa
3. torna-se Administrador da Empresa
4. configura padrões da Empresa
5. cria 1..N Lojas
6. cada Loja herda automaticamente os padrões
7. Administrador convida membros
8. define o papel do convidado
9. se Gestor, atribui 1..N Lojas
10. convidado aceita e passa a operar dentro do papel + escopo
```

Gestores adicionais não criam uma nova Empresa para representar a mesma organização.

## Eventos e autorização

Administrador pode criar eventos para toda a Empresa ou para qualquer conjunto de Lojas.

Gestores podem criar eventos apenas dentro das Lojas às quais possuem acesso, caso essa capacidade esteja habilitada para o papel.

A autorização deve validar tanto a capacidade quanto o escopo.

## Separação do PDV

A plataforma de fidelidade não substitui o PDV.

```text
PDV
- venda
- produtos
- pagamentos
- estoque
- caixa
- fiscal

Plataforma de fidelidade
- cliente
- regras de pontos
- níveis
- campanhas
- saldo
- resgates
- indicadores de fidelidade
```

A integração ocorre através da API. O sistema externo envia fatos da venda; a plataforma resolve parâmetros, eventos e calcula a fidelidade.

## Arquitetura de aplicação

A direção continua sendo um monólito modular Django, não microserviços.

```text
Interface Web / Django Templates
                │
                ├──── Camada de domínio/serviços ──── PostgreSQL
                │
REST API / DRF ─┘
```

Views HTML e endpoints REST devem reutilizar as mesmas operações de domínio. Regras de fidelidade não devem ser duplicadas entre interface web e API.

## Prioridades para a entrega

Considerando o prazo curto, a prioridade é entregar uma vertical coerente:

```text
Empresa
↓
Loja
↓
Configuração efetiva
↓
Cliente
↓
Compra via API
↓
Cálculo de pontos
↓
Evento temporário
↓
Dashboard
```

Funcionalidades sofisticadas devem ser adicionadas somente se não comprometerem essa vertical principal.

## Decisões ainda a detalhar

Devem ganhar Issues próprias antes da implementação:

- modelagem definitiva de `MembroEmpresa` e `AcessoLoja`;
- estrutura concreta dos parâmetros tipados;
- níveis de fidelidade configuráveis;
- política de conflito/composição entre eventos;
- auditoria de alterações de configuração;
- vigência/versionamento de configurações;
- permissões finas por papel;
- estratégia definitiva para credenciais de integração.
