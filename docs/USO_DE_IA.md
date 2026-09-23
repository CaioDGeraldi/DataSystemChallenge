# Uso de IA

A inteligência artificial é utilizada como ferramenta de apoio ao desenvolvimento, não como substituta da equipe. O uso acontece ao longo do processo em atividades como planejamento, análise de requisitos, discussão de arquitetura, investigação, implementação assistida, geração e revisão de testes, revisão técnica e preparação de documentação.

A responsabilidade pelas decisões, pelo entendimento do sistema e pela validação do resultado permanece com a equipe. O processo não consiste em solicitar que a IA gere o sistema inteiro e apenas aceitar o resultado ao final.

## Princípios de uso consciente

O uso de IA no projeto segue estes princípios:

- o problema e os requisitos são entendidos antes da implementação;
- decisões funcionais e arquiteturais são fechadas pela equipe;
- cada implementação parte de uma Issue com objetivo, escopo, critérios de aceite e dependências;
- a IA recebe as decisões já vigentes e não deve ampliar o escopo silenciosamente;
- quando surge uma decisão não especificada, a implementação deve parar para que a equipe decida antes de continuar;
- sugestões e código gerados com auxílio de IA são revisados antes de serem integrados;
- resultados são validados por comandos e testes reais, preferencialmente no mesmo banco de referência do projeto;
- uma afirmação da IA não é considerada evidência de funcionamento;
- alterações entram na `main` somente após revisão do diff e Pull Request;
- a equipe deve ser capaz de explicar e defender tecnicamente tudo que foi integrado.

Fluxo resumido:

```text
Entender o problema
→ fechar decisões
→ criar Issue
→ criar branch
→ usar IA como apoio
→ executar validações
→ revisar o diff
→ abrir Pull Request
→ revisar
→ Squash and merge
```

## Como as ferramentas são utilizadas

### ChatGPT

É utilizado principalmente para:

- discutir requisitos e regras de negócio;
- comparar alternativas de arquitetura;
- identificar decisões ainda não fechadas;
- estruturar Issues e critérios de aceite;
- revisar implementações e diffs;
- identificar inconsistências, lacunas de segurança e desvios de escopo antes do merge;
- explicar conceitos técnicos para que a equipe compreenda as decisões;
- apoiar a documentação e a preparação para apresentação.

O ChatGPT não é tratado como fonte automática de verdade. Quando uma regra depende de informação externa ou de uma decisão do projeto, ela deve ser verificada ou explicitamente decidida antes de virar implementação.

### Codex / GPT-6 Astra

O Codex é utilizado como ferramenta de implementação assistida. Nas execuções mais recentes, o modelo GPT-6 Astra também foi utilizado dentro desse fluxo para tarefas de implementação e revisão que exigem maior contexto técnico.

Essas ferramentas recebem uma Issue, a branch correta, as decisões já fechadas, o escopo e os critérios de aceite. A orientação do projeto é que:

- preservem os contratos existentes;
- implementem de forma incremental;
- não inventem requisitos;
- não tomem decisões arquiteturais pendentes por conta própria;
- não ampliem o escopo silenciosamente;
- reportem bloqueios e dúvidas antes de escolher uma solução que altere o domínio;
- não substituam a validação local feita pela equipe;
- produzam código que posteriormente será revisado e validado antes da integração.

A escolha do modelo ou da intensidade de raciocínio pode variar conforme a complexidade da tarefa, mas isso não altera o processo de responsabilidade: a ferramenta auxilia a execução; a equipe continua responsável por decidir, compreender, testar e aprovar.

## Exemplos de decisões interrompidas ou corrigidas antes do merge

Um exemplo ocorreu na modelagem de `Cliente`, `Gestor`, `Loja` e `Empresa`: durante a implementação surgiu a necessidade de definir a política de exclusão dos relacionamentos (`on_delete`). Em vez de escolher silenciosamente entre `CASCADE` e `PROTECT`, a implementação foi interrompida. A equipe decidiu utilizar `PROTECT` para evitar exclusões destrutivas e só então o desenvolvimento continuou.

Outro exemplo ocorreu na F2.06. A primeira implementação das credenciais de integração tornava `Empresa` e o campo `escopo` imutáveis, mas a revisão identificou que uma credencial `LOJAS` ainda poderia ter seu conjunto efetivo de Lojas alterado pelos caminhos normais do domínio. O problema foi tratado como blocker antes do commit. A implementação foi corrigida para congelar o conjunto emitido de Lojas e exigir o fluxo `desativar credencial antiga → criar nova credencial` para qualquer mudança de escopo. Somente depois da correção, da nova revisão e dos testes a alteração foi integrada.

Na F3.01, o GPT-6 Astra interrompeu a implementação antes de alterar código porque a Issue ainda não definia o limite monetário de `Compra.valor` nem o tamanho máximo de `identificador_externo`. A equipe fechou explicitamente `DecimalField(max_digits=12, decimal_places=2)` e limite de 255 caracteres antes da continuação. Durante a revisão posterior, foi identificado outro blocker: embora os retries não alterassem a Compra, o model ainda permitia reescrever fatos históricos já persistidos pelos caminhos normais de `save()`. A implementação foi corrigida para congelar Loja, Cliente, credencial de origem, identificador externo, valor, instante da venda e `criada_em`, sem invalidar Compras históricas quando a credencial de origem fosse desativada.

Esses casos representam o comportamento esperado: a IA não deve decidir silenciosamente uma regra faltante e um resultado que passou por geração automatizada ainda pode ser rejeitado ou corrigido durante a revisão.

## Validação independente da IA

A saída da IA não é considerada prova de que uma alteração funciona. O projeto utiliza validações reais, conforme o tipo de mudança, como:

```text
uv run python manage.py check
uv run python manage.py makemigrations --check
uv run python manage.py migrate
uv run python manage.py test
git diff --check
uv lock --check
```

Os testes são executados com PostgreSQL, que é o banco de referência da aplicação. Migrations, constraints, validações, relacionamentos, autorização e isolamento multiempresa também são revisados no diff antes do Pull Request.

Features podem exigir gates adicionais específicos. Na F2.06, por exemplo, além dos gates gerais foi validado o schema OpenAPI com:

```text
uv run python manage.py spectacular --file /tmp/datasystem-openapi.yml --validate
```

Na mesma fase, foram executados testes específicos da API e da integração, seguidos pela suíte completa do projeto. A aprovação da ferramenta que implementou a mudança não foi utilizada como evidência; os resultados reais dos testes e a revisão do diff foram utilizados para decidir se a alteração estava pronta para commit e merge.

Na F3.01, após a implementação inicial e a correção de imutabilidade histórica, foram executados 39 testes focais e 261 testes na suíte completa. Também foram validados `check`, `makemigrations --check`, aplicação/estado da migration `fidelidade.0001_initial`, `git diff --check`, `uv lock --check` e o schema OpenAPI com `spectacular --validate`. A concorrência idempotente foi coberta com PostgreSQL e conexões independentes, verificando tanto requests equivalentes quanto payloads divergentes para a mesma chave.

## Separação de responsabilidades

O uso de IA no projeto pode ser resumido assim:

```text
Equipe
├── define o problema
├── fecha requisitos e decisões
├── prioriza escopo
├── executa e interpreta validações
├── revisa o diff
└── assume responsabilidade pelo resultado

IA
├── ajuda a analisar
├── sugere alternativas
├── implementa tarefas especificadas
├── auxilia testes e documentação
└── aponta riscos, dúvidas e inconsistências
```

A ferramenta pode produzir código, sugerir uma arquitetura ou identificar um problema, mas nenhuma dessas ações transfere a responsabilidade técnica para a IA.

## Registro de uso

| Data | Atividade | Ferramenta | Como ajudou | Decisão/ajuste da equipe |
| --- | --- | --- | --- | --- |
| Não registrada | Planejamento e modelagem inicial | ChatGPT | Apoiou a discussão de requisitos, escopo, arquitetura e organização do desenvolvimento. | A equipe revisou as propostas e transformou as decisões aprovadas em Issues e critérios de aceite. |
| 2026-09-22 | Bootstrap Django e autenticação por CPF (Issue #7) | ChatGPT e Codex | ChatGPT apoiou a definição da arquitetura; Codex auxiliou na configuração, implementação do `CustomUser`, validação de CPF e testes. | A equipe definiu `CustomUser` antes da migration inicial, autenticação por CPF, PostgreSQL como banco de referência e isolamento da infraestrutura. O código foi revisado e validado antes do merge. |
| 2026-09-22 | Modelagem inicial de Empresa, Loja, Cliente e Gestor (Issue #9) | ChatGPT e Codex | Apoiou a modelagem das entidades, implementação dos relacionamentos, validação de CNPJ e testes de domínio. | A equipe separou identidade (`Usuario`) de perfis de domínio, decidiu `PROTECT` para os relacionamentos e manteve Compra, PDV e fidelidade fora do escopo. |
| 2026-09-22 | Consolidação da arquitetura multiempresa, parâmetros e API (Issue #12) | ChatGPT | Apoiou a reorganização do produto como plataforma independente, multiempresa, configurável e API-first. | A equipe definiu Empresa como tenant, `1..N` Lojas, herança de parâmetros, overrides, eventos/campanhas, papel + escopo, API REST versionada, OpenAPI e idempotência. |
| 2026-09-22 | Reconciliação do domínio multiempresa (Issue #14 / F2.03A) | ChatGPT e Codex | Apoiou a revisão da modelagem anterior e a implementação de uma estrutura compatível com múltiplas Empresas por identidade. | A equipe consolidou `Usuario` global, `Cliente = Usuario + Empresa`, `MembroEmpresa`, papéis `ADMINISTRADOR`/`GESTOR`, `AcessoLoja`, escopo corporativo implícito do Administrador, validações de tenant e `PROTECT`. |
| 2026-09-22 | Cadastro e autenticação por contexto multiempresa (Issue #11 / F2.03B) | ChatGPT e Codex | Apoiou a definição e implementação do cadastro por Empresa, autenticação global por CPF e seleção de contexto. | A equipe definiu reutilização segura de `Usuario`, sessão com apenas `tipo_contexto`, `empresa_id` e `vinculo_id`, revalidação do vínculo no banco e distinção entre contexto de Cliente e Gestão. |
| 2026-09-22 | Roadmap técnico e de produto (Issue #15) | ChatGPT | Apoiou a organização das fases e prioridades P0/P1/P2. | A equipe protegeu a vertical principal Empresa → Loja → Configuração → API → Compra → Pontos → Evento → Níveis/Resgate → Dashboard e manteve a FATECalçados como cenário, não regra do domínio. |
| 2026-09-22 | Política e registro de uso de IA (Issue #17) | ChatGPT | Apoiou a formalização do processo já utilizado no projeto. | A equipe registrou que IA é apoio, não fonte de verdade; decisões faltantes devem interromper a implementação; validações reais, revisão de diff e Pull Request são obrigatórias antes da integração. |
| 2026-09-22 | Onboarding de Empresa e primeira Loja (Issue #21 / F2.04A) | ChatGPT e Codex | Apoiou a especificação e implementação do fluxo de criação ou reutilização de identidade, Empresa, primeira Loja e Administrador. | A equipe definiu operação atômica, slug gerado no backend, Administrador com escopo corporativo e criação de Lojas adicionais restrita ao tenant ativo. |
| 2026-09-22 | Convites de membros e atribuição de Lojas (Issue #23 / F2.04B) | ChatGPT e Codex | Apoiou a modelagem do convite, token, aceite, revogação, concorrência e testes. | A equipe definiu CPF como identificador, token bruto exibido apenas na criação, hash persistido, validade de 7 dias, aceite atômico e `GESTOR` com `1..N` Lojas explícitas. |
| 2026-09-22 | Parâmetros hierárquicos de fidelidade (Issue #25 / F2.05) | ChatGPT e GPT-6 Astra | Apoiou a especificação e implementação de configuração tipada `padrão do produto → Empresa → override de Loja`. | A equipe definiu `Decimal`, ausência de override como herança, `0.00` como valor válido, resolução somente leitura e nenhuma regra específica de Bronze/Prata/Ouro hardcoded. Uma falha de import encontrada nos testes foi corrigida antes da integração. |
| 2026-09-22 a 2026-09-23 | Base da API REST e credenciais de integração (Issue #28 / F2.06) | ChatGPT e GPT-6 Astra | Apoiou a especificação e implementação de DRF, `X-API-Key`, autenticação de integração, escopos `EMPRESA`/`LOJAS`, OpenAPI, Swagger, ReDoc, erros e testes. | A equipe separou integração de `Usuario`, exigiu hash do segredo, isolamento multiempresa e imutabilidade do escopo emitido. A revisão encontrou uma possibilidade de alterar o conjunto de Lojas após a emissão; o blocker foi corrigido antes do commit. Foram validados testes específicos, suíte completa e schema OpenAPI antes do Squash and merge. |
| 2026-09-23 | Compra e idempotência pela API (Issue #34 / F3.01) | ChatGPT e GPT-6 Astra | ChatGPT apoiou a especificação do contrato, revisão técnica e análise de idempotência/concorrência; Astra implementou o domínio, endpoint, testes e documentação dentro da Issue. | Astra interrompeu a implementação diante de limites não especificados e a equipe definiu os valores antes de continuar. A revisão encontrou mutabilidade indevida dos fatos históricos; o blocker foi corrigido antes do commit. Foram validados 39 testes focais, 261 testes totais, migrations, diff, lock e OpenAPI antes do Squash and merge. |

## Estado atual

Até a conclusão da F3.01, a IA participou de planejamento, documentação, implementação assistida e revisão de várias camadas do produto, incluindo domínio multiempresa, autenticação por contexto, onboarding, convites, parâmetros hierárquicos, fundação da API REST e o primeiro recurso transacional idempotente de Compra.

O processo utilizado nessas entregas permanece o mesmo: requisitos e decisões são fechados antes da implementação; a IA atua dentro do escopo estabelecido; dúvidas que alteram contrato ou domínio interrompem a execução; a saída é validada independentemente; o diff é revisado; e somente então a alteração pode chegar à `main` por Pull Request e Squash and merge.

## Responsabilidade da equipe

Mesmo quando parte do código é produzida com auxílio de IA, a responsabilidade técnica continua sendo da equipe. Isso significa compreender o comportamento implementado, saber justificar as decisões adotadas, reconhecer limitações e conseguir explicar como o sistema foi testado.

O critério adotado é simples: código ou decisão que a equipe não consegue explicar, revisar ou validar não deve ser integrado ao projeto.
