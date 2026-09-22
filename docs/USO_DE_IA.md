# Uso de IA

A inteligência artificial é utilizada como ferramenta de apoio ao desenvolvimento, não como substituta da equipe. O uso acontece ao longo do processo em atividades como planejamento, análise de requisitos, discussão de arquitetura, investigação, geração assistida de código e testes, revisão técnica e preparação de documentação.

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
- não se considera uma afirmação da IA como evidência de funcionamento;
- alterações entram na `main` somente após revisão do diff e Pull Request;
- a equipe deve ser capaz de explicar e defender tecnicamente tudo que foi integrado.

O fluxo utilizado no projeto é, de forma resumida:

```text
Entender o problema
→ fechar decisões
→ criar Issue
→ criar branch
→ usar IA como apoio à implementação
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
- explicar conceitos técnicos para que a equipe compreenda as decisões;
- apoiar a documentação e a preparação para apresentação.

O ChatGPT não é tratado como fonte automática de verdade. Quando uma regra depende de informação externa ou de uma decisão do projeto, ela deve ser verificada ou explicitamente decidida antes de virar implementação.

### Codex

É utilizado principalmente como ferramenta de implementação assistida. Ele recebe uma Issue, a branch correta, as decisões já fechadas, o escopo e os critérios de aceite.

A orientação do projeto é que o Codex:

- preserve os contratos existentes;
- implemente de forma incremental;
- não invente requisitos;
- não tome decisões arquiteturais pendentes por conta própria;
- não amplie o escopo silenciosamente;
- reporte bloqueios e dúvidas antes de escolher uma solução que altere o domínio;
- produza código que posteriormente será revisado e validado pela equipe.

Um exemplo real ocorreu na modelagem de `Cliente`, `Gestor`, `Loja` e `Empresa`: durante a implementação surgiu a necessidade de definir a política de exclusão dos relacionamentos (`on_delete`). Em vez de escolher silenciosamente entre `CASCADE` e `PROTECT`, a implementação foi interrompida. A equipe decidiu utilizar `PROTECT` para evitar exclusões destrutivas e só então o desenvolvimento continuou.

## Validação independente da IA

A saída da IA não é considerada prova de que uma alteração funciona. O projeto utiliza validações reais, de acordo com o tipo de mudança, como:

```text
uv run python manage.py check
uv run python manage.py makemigrations --check
uv run python manage.py migrate
uv run python manage.py test
git diff --check
uv lock --check
```

Os testes são executados com PostgreSQL, que é o banco de referência da aplicação. Migrations, constraints, validações e relacionamentos também são revisados no diff antes do Pull Request.

## Registro de uso

| Data | Atividade | Ferramenta | Como ajudou | Decisão/ajuste da equipe |
| --- | --- | --- | --- | --- |
| Não registrada | Planejamento e modelagem inicial | ChatGPT | Apoiou a discussão de requisitos, escopo, arquitetura e organização do desenvolvimento. | A equipe revisou as propostas e transformou as decisões aprovadas em Issues e critérios de aceite. |
| 2026-09-22 | Bootstrap Django e autenticação por CPF (Issue #7) | ChatGPT e Codex | ChatGPT apoiou a definição da arquitetura; Codex auxiliou na configuração, implementação do `CustomUser`, validação de CPF e testes. | A equipe definiu `CustomUser` antes da migration inicial, autenticação por CPF, PostgreSQL como banco de referência e isolamento da infraestrutura. O código foi revisado e validado antes do merge. |
| 2026-09-22 | Modelagem de Empresa, Loja, Cliente e Gestor (Issue #9) | ChatGPT e Codex | Apoiou a modelagem das entidades, implementação dos relacionamentos, validação de CNPJ e testes de domínio. | A equipe definiu a separação entre identidade (`Usuario`) e perfis de domínio, decidiu `PROTECT` para os relacionamentos e manteve Compra, PDV e fidelidade fora do escopo. A implementação passou por revisão do diff e testes no PostgreSQL antes do merge. |
| 2026-09-22 | Planejamento do cadastro de Cliente e login por contexto (Issue #11) | ChatGPT | Apoiou a definição do fluxo de cadastro, autenticação, autorização por contexto, uso de sessão e limites de escopo. | A equipe decidiu separar autenticação de autorização, identificar a Empresa por `slug`, criar `Usuario + Cliente` de forma atômica e manter onboarding/convite de Gestor para uma Issue posterior. |

## Responsabilidade da equipe

Mesmo quando parte do código é produzida com auxílio de IA, a responsabilidade técnica continua sendo da equipe. Isso significa compreender o comportamento implementado, saber justificar as decisões adotadas, reconhecer limitações e conseguir explicar como o sistema foi testado.

O critério adotado é simples: código ou decisão que a equipe não consegue explicar, revisar ou validar não deve ser integrado ao projeto.
