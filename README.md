# Retorna | Multi-company Loyalty Platform

**Retorna** is a team-developed, configurable loyalty platform built for the Data System Challenge. It connects point-of-sale, ERP or commerce systems to a loyalty domain through a versioned API.

> **Scope:** This repository contains a demonstrator and its development history. It is not presented as a production service with real customers. **FATECalçados** is a fictitious demonstration tenant.

## What it does

- Supports companies with multiple stores and store-level policy overrides.
- Records purchases, point accrual and expiration, events/campaigns, loyalty tiers, redemptions and reversals.
- Exposes versioned REST endpoints and OpenAPI documentation for external integrations.
- Includes customer-facing pages, dashboards, permissions and a PostgreSQL audit trail.

## Technical highlights

| Area | Implementation |
| --- | --- |
| Backend | Python, Django, Django REST Framework |
| Persistence | PostgreSQL, constraints, explicit transactions and locking |
| API | Versioned endpoints, OpenAPI through drf-spectacular |
| Concurrency | Idempotency keys, row locking and PostgreSQL advisory locks in redemption flows |
| Frontend | Django templates, JavaScript, Sass, Chart.js and Vite |
| Quality | Backend/frontend GitHub Actions, Django tests, PostgreSQL concurrency scenarios |

See the [technical case study](docs/RECRUITER_CASE_STUDY.md) for concrete source links and the problems addressed.

## Run locally (standalone setup)

**Requirements:** Python 3.12+, [uv](https://docs.astral.sh/uv/), Docker, Node.js 22 and npm. You do **not** need access to the private `FractawModulesInfrastructure` repository for the standalone database setup below.

1. Prepare local environment variables:

   ```sh
   cp .env.example .env.datasystem
   ```

   Edit `.env.datasystem` with your **own** `DJANGO_SECRET_KEY` and `POSTGRES_PASSWORD`. Use `POSTGRES_HOST=127.0.0.1`, `POSTGRES_PORT=5434`, and keep `DJANGO_DEBUG=true` and `DJANGO_SECURE_SSL_REDIRECT=false` for local HTTP only. Never commit this file.

2. Start an isolated PostgreSQL 17 instance:

   ```sh
   docker run -d --name retorna-postgres \
     --env-file .env.datasystem \
     -p 127.0.0.1:5434:5432 \
     -v retorna-postgres-data:/var/lib/postgresql/data \
     postgres:17
   ```

   This is a Bash example. For Windows, use WSL/Git Bash or adapt the line continuations. The PostgreSQL volume persists independently of the container.

3. Install Python dependencies and build the frontend assets:

   ```sh
   uv sync --locked
   npm ci
   npm run heroku-postbuild
   ```

4. Load the local configuration and migrate the database:

   ```sh
   set -a
   . ./.env.datasystem
   set +a
   uv run python manage.py migrate
   uv run python manage.py runserver
   ```

   Open `http://127.0.0.1:8000/`. The environment variables above apply to the current shell. Do not treat these development settings as production defaults.

### Run checks and tests

With the same environment variables loaded and PostgreSQL running:

```sh
uv run python manage.py check
uv run python manage.py makemigrations --check
uv run python manage.py spectacular --file /tmp/retorna-openapi.yml --validate
uv run python manage.py test --noinput
```

Continuous integration additionally builds frontend assets and runs interface validations. See [the CI workflow](.github/workflows/ci.yml) and the [Actions history](https://github.com/CaioDGeraldi/DataSystemChallenge/actions).

## Architecture and documentation

The application follows a **modular Django monolith**. Domain rules are shared by the web interface and API, and PostgreSQL is the reference database. Integration clients provide business events; Retorna owns loyalty calculations and history.

- [Technical case study for reviewers](docs/RECRUITER_CASE_STUDY.md)
- [Product architecture](docs/ARQUITETURA_PRODUTO.md) (PT-BR)
- [API design and conventions](docs/API.md) (PT-BR)
- [Data model](docs/MODELAGEM_DE_DADOS.md) (PT-BR)
- [API integration contract](docs/INTEGRACAO_API.md) (PT-BR)
- [Frontend documentation](docs/FRONTEND.md) (PT-BR)
- [Roadmap](docs/ROADMAP.md) (PT-BR)
- [Heroku demonstration runbook](docs/DEPLOY_HEROKU.md) (PT-BR)
- [Development workflow](docs/workflow-desenvolvimento.md) (PT-BR)
- [AI-assisted development disclosure](docs/USO_DE_IA.md) (PT-BR)
- [Contributing](CONTRIBUTING.md) (PT-BR)

## Team and authorship

Retorna was built as a **collaborative team project**. The repository includes issues, pull requests and development notes. It also openly documents the team's use of AI assistance. Architecture, implementation and testing claims should be evaluated against the source, rather than attributed to any one participant without examining the contribution history.

**Naming:** `DataSystemChallenge` refers to the repository and challenge; `Retorna` to the product; `FATECalçados` to the fictitious demo company.
