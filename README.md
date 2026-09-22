# DataSystem Challenge

Plataforma de fidelidade multiempresa desenvolvida para o desafio da Data System. O produto é tratado como ferramenta independente: Empresas podem possuir `1..N` Lojas, políticas configuráveis, overrides por Loja, eventos/campanhas temporárias e integrações por API.

A FATECalçados é utilizada como cenário e conjunto de dados de demonstração, não como regra fixa do produto.

O repositório reúne:
- código da aplicação;
- arquitetura e decisões de produto;
- documentação da API;
- coordenação da equipe;
- convenções de trabalho no GitHub;
- Issues, Pull Requests e histórico do projeto;
- orientação para uso do GitHub Projects em formato Kanban.

## Desenvolvimento local

Requisitos: `uv`, Docker com Compose e acesso ao repositório `FractawModulesInfrastructure` para usar o Compose de referência. O banco do DataSystemChallenge usa um projeto Compose e um volume próprios.

1. Execute `uv sync`.
2. Copie `.env.example` para `.env.datasystem` e preencha `DJANGO_SECRET_KEY` e `POSTGRES_PASSWORD` com valores locais. O arquivo local é ignorado pelo Git.
3. Suba o PostgreSQL com `docker compose -f ../FractawModulesInfrastructure/compose.yml --env-file .env.datasystem -p datasystemchallenge up -d db`.
4. Carregue as variáveis com `set -a; . ./.env.datasystem; set +a` e execute `uv run python manage.py migrate` e `uv run python manage.py runserver`.

Use `POSTGRES_HOST=127.0.0.1` e `POSTGRES_PORT=5434` para o acesso local conforme o exemplo. O projeto `datasystemchallenge` mantém o volume do PostgreSQL separado do projeto `fractawmodules`. Para validar a base, execute `uv run python manage.py check`, `uv run python manage.py makemigrations --check` e `uv run python manage.py test` após carregar as variáveis.

## Arquitetura e API

- [Roadmap do produto](docs/ROADMAP.md)
- [Arquitetura do produto](docs/ARQUITETURA_PRODUTO.md)
- [Estratégia e convenções da API](docs/API.md)

A direção arquitetural é manter um monólito modular Django, com PostgreSQL como banco de referência e API REST versionada como interface de primeira classe para integrações externas. Regras de domínio devem ser compartilhadas entre a interface web e a API.

## Kanban

[DataSystem Kanban](https://github.com/users/CaioDGeraldi/projects/6/views/1)

Estados oficiais: `Backlog` → `Em andamento` → `Revisão` → `Concluído`.

## Modelos e processo

- [MVP](docs/modelos/MVP.md)
- [Sprint](docs/modelos/SPRINT.md)
- [Workflow de desenvolvimento](docs/workflow-desenvolvimento.md)
- [Uso de IA](docs/USO_DE_IA.md)
- [Coordenação da equipe](docs/COORDENACAO.md)
- [Guia de contribuição](CONTRIBUTING.md)
