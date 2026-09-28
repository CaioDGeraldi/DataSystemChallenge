# Demonstração no Heroku — Issue #106

Este runbook descreve como provisionar o ambiente, executar o Seed inicial e
validar a demonstração **após a revisão e os gates locais**. Use os procedimentos
conforme a etapa da operação, preservando a execução única do Seed.

## Pré-requisitos e provisionamento

- Heroku CLI instalada e conta Heroku autenticada pelo operador.
- Aplicação **Cedar criada no account pessoal**, com stack **heroku-26**.
- Assinatura Eco disponível para usar um dyno web Eco. Se indisponível, parar e
  decidir o custo/tier com o responsável; não escolher outro plano silenciosamente.
- **Heroku Postgres essential-0** dedicado à demonstração, inicialmente limpo.
- Revisão e gate completo aprovados; branch `001/tech/106-deploy-heroku`
  com a implementação revisada disponível para deploy antes do merge.

Nos comandos abaixo, `APP` representa o nome real da aplicação, definido pelo operador.
Se ainda não existe, criar pelo Dashboard no account pessoal, selecionando Cedar;
não criar uma aplicação Fir/container. Para a aplicação criada:

```bash
heroku stack:set heroku-26 --app "$APP"
heroku buildpacks:clear --app "$APP"
heroku buildpacks:add --index 1 heroku/nodejs --app "$APP"
heroku buildpacks:add --index 2 heroku/python --app "$APP"
heroku buildpacks --app "$APP"
heroku addons:create heroku-postgresql:essential-0 --app "$APP"
```

Criar o add-on somente se ainda não provisionado. A ordem deve ser exatamente
`1. heroku/nodejs`, `2. heroku/python`: Python é a linguagem principal e fica por último.
Conferir stack/generation no Dashboard antes do primeiro build.

## Config vars

Cadastrar pelo Dashboard; não copiar secrets para Git, Issue, PR, logs ou comandos
registrados em histórico. Use o hostname real exibido pelo Heroku, incluindo o
sufixo atribuído à aplicação, sem supor que ele coincide com o nome do app.

| Nome | Configuração |
| --- | --- |
| `DJANGO_SECRET_KEY` | Secret aleatório forte, exclusivo do ambiente; mantido fora do repositório. |
| `DJANGO_DEBUG` | `false`. |
| `DATABASE_URL` | Fornecida pelo add-on Postgres; não copiar nem manter manualmente. |
| `DJANGO_ALLOWED_HOSTS` | Hostname explícito, sem esquema, caminho ou wildcard; múltiplos separados por vírgula. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Origens completas HTTPS, sem caminho; múltiplas separadas por vírgula. |
| `DJANGO_SECURE_SSL_REDIRECT` | `true` (também é o default com DEBUG desabilitado). |
| `RETORNA_SEED_SENHA` | Temporária, exclusiva das contas fictícias; cadastrar somente no provisionamento inicial e remover após a tentativa de Seed. |

Não configurar `RETORNA_SEED_CREDENCIAL_ARQUIVO`, `DISABLE_COLLECTSTATIC` nem
`POSTGRES_*` no Heroku. `PORT` é fornecida pelo runtime.

`DATABASE_URL` não vazia substitui integralmente `POSTGRES_*`, aceita somente
PostgreSQL e exige `sslmode=require` (TLS, conforme conexão Heroku Postgres).
Ausente ou vazia, usa os cinco `POSTGRES_*` existentes, sem SQLite e sem forçar
SSL no banco local. O `.env.example` conserva HTTP local com `DJANGO_DEBUG=true`
e redirect desabilitado; Django não carrega esse arquivo automaticamente.

Hosts e origens são listas por vírgula, com espaços e entradas vazias ignorados.
Sem hosts informados, DEBUG permite somente localhost/loopback; produção exige
hosts explícitos. Cookies de sessão e CSRF são seguros com DEBUG desabilitado,
mesmo se o redirect for temporariamente desabilitado. `X-Forwarded-Proto: https`
informa ao Django que a requisição original é segura, evitando loop no router.
Essa confiança pressupõe o proxy Heroku; não expor Gunicorn diretamente à internet.
Não há HSTS adicional configurado.

## CI — GitHub Actions

O workflow `.github/workflows/ci.yml` roda em PRs direcionadas à `main` e em pushes
na `main`, com os checks estáveis **Backend** e **Frontend**, independentes e
paralelos. Execuções antigas da mesma PR/branch são canceladas quando chega uma revisão.

Backend usa Python 3.12, uv e PostgreSQL `17` como service com health check e porta
local. Essa versão é uma escolha somente de CI, sem impor versão ao banco de produção.
As credenciais são fictícias e descartáveis. `DJANGO_DEBUG=true` e redirect desabilitado
preservam os testes HTTP locais; não mudam a configuração de produção.
O job valida lockfile, Django, migrations, OpenAPI e executa a suíte completa.
Como os testes de interface exigem arquivos reais em `frontend/dist`, ele também
prepara os assets com Node 22 e o wrapper existente antes dos testes.

Frontend usa Node 22, `npm ci`, `npm run heroku-postbuild` e os quatro validators
existentes. Não há dependência nem transferência de artifacts entre jobs.
O CI tem somente `contents: read`, não recebe secrets de produção, não executa
o comando de provisionamento do Seed e não faz deploy. Os testes existentes do
Seed continuam na suíte, com seu próprio isolamento no banco de testes.

## Build, primeiro deploy controlado e release

O wrapper raiz não contém dependências frontend. Node **22.x** executa
`npm --prefix frontend ci --include=dev` e `npm --prefix frontend run build` pelo
hook `heroku-postbuild`; os lockfiles e dependências reais continuam em `frontend/`.
Python **3.12** usa `pyproject.toml` + `uv.lock`, e o buildpack executa `collectstatic`
depois do Vite. Não versionar `frontend/dist/` nem `staticfiles/`.

WhiteNoise vem imediatamente após SecurityMiddleware e serve `staticfiles/` pelo
WSGI, com `CompressedStaticFilesStorage`. Os nomes estáveis são preservados,
sem manifesto de hashes; o cache padrão é curto (60 segundos). Não há servidor
Vite/runserver no runtime, CDN ou storage externo.

Para a **primeira validação antes do merge**, depois dos gates locais, CI da PR
verde e revisão, conectar o repositório no Dashboard Heroku conforme a seção de CD
abaixo. Em **Manual Deploy**, selecionar `001/tech/106-deploy-heroku` e executar
**Deploy Branch**. Manter Automatic Deploys desabilitado durante essa validação
inicial. O operador deve conferir os checks da PR antes de acionar o deploy manual.

Após o deploy controlado, conferir a release e ativar o dyno Eco já autorizado:

```bash
heroku releases --app "$APP"
heroku ps:scale web=1:eco --app "$APP"
heroku ps --app "$APP"
```

Validar a branch antes do merge. No log do build, confirmar Node → Vite → Python/uv
→ collectstatic. Confirmar a release bem-sucedida e consultar os logs da release
no Dashboard em caso de falha; não seguir para o Seed com migrations pendentes.

O `Procfile` contém:

```procfile
release: python manage.py migrate --noinput
web: gunicorn config.wsgi
```

Gunicorn usa automaticamente `0.0.0.0:$PORT` quando `PORT` existe, sem porta fixa
ou tuning de workers. A release aplica somente migrations. Não executa Seed nem
collectstatic. Falha na release precisa ser resolvida antes de validar a aplicação.

## CD definitivo — GitHub Integration do Heroku

Fluxo: feature branch → PR → GitHub Actions CI → review → **Squash and merge**
→ `main` → GitHub Actions CI novamente → **todos os checks verdes** → Heroku
Automatic Deploy → Node/Vite → Python/uv + collectstatic → release/migrate → Gunicorn.

Configuração pelo operador na aba **Deploy** do Dashboard Heroku:

1. Selecionar GitHub como método de deploy e conectar a conta GitHub.
2. Selecionar o repositório `CaioDGeraldi/DataSystemChallenge`.
3. Após validar a branch e integrar a PR, selecionar `main` em Automatic Deploys.
4. Marcar **Wait for CI to pass before deploy** para aguardar todos os checks verdes.
5. Habilitar **Enable Automatic Deploys**, mantendo a espera pelo CI marcada.
6. Não cadastrar `HEROKU_API_KEY` ou outra credencial de deploy no GitHub Actions.

O primeiro Manual Deploy valida a branch da Issue; o fluxo definitivo acompanha
somente `main` após CI verde,
sem push para o remote Heroku ou deploy pelo Actions. Confirmar a primeira execução
automática após o merge no Dashboard. Ver [integração oficial GitHub → Heroku](https://devcenter.heroku.com/articles/github-integration#automatic-deploys).

Após a primeira execução do workflow na PR, configurar no GitHub os checks
**Backend** e **Frontend** como obrigatórios para `main`, quando disponível.
A proteção de branch não é configurada por este código.

## Seed: migrations → uma execução → remover senha

1. Confirmar migrations aplicadas e banco de demonstração limpo.
2. Escolher `DATA_BASE` em `YYYY-MM-DD`, próxima do provisionamento/apresentação.
3. Cadastrar temporariamente `RETORNA_SEED_SENHA` pelo Dashboard, sem compartilhar
   o valor em logs/documentos. Usar senha exclusiva da demonstração.
4. Executar **uma única vez**, acompanhando o resultado:

   ```bash
   heroku run --exit-code --app "$APP" -- \
     python manage.py seed_fatecalcados --data-base "$DATA_BASE"
   ```

5. Remover a variável mesmo em caso de falha e confirmar sua ausência no Dashboard:

   ```bash
   heroku config:unset RETORNA_SEED_SENHA --app "$APP"
   ```

Se houver erro ou dúvida sobre o término, investigar banco/logs antes de qualquer
nova execução; não usar reset nem repetir automaticamente. O Seed não faz parte
de build, release, start ou redeploy. O filesystem do dyno é efêmero: não usá-lo
para persistir a credencial do Seed. Emitir e capturar a credencial de integração
pelo fluxo real de Gestão para o smoke autenticado, guardando-a fora do repositório.
Contas, CPFs sintéticos e contrato completo: [Seed FATECalçados V2](SEED_FATECALCADOS.md).

## Gates locais e smoke no ambiente publicado

Com Node 22 e Python 3.12, executar na raiz, após carregar o ambiente **local**
(`DJANGO_DEBUG=true`, PostgreSQL local):

```bash
uv sync --locked
uv lock --check
npm ci
npm run heroku-postbuild
npm --prefix frontend run build
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py test --noinput
uv run python manage.py spectacular --file /tmp/datasystem-openapi.yml --validate
node frontend/scripts/validate-interface.mjs
node frontend/scripts/validate-dashboard-charts.mjs
node frontend/scripts/validate-dashboard-filter.mjs
node frontend/scripts/validate-cliente.mjs
DJANGO_DEBUG=false uv run python manage.py collectstatic --noinput --clear
uv run gunicorn --check-config config.wsgi
git diff --check
```

Para smoke local de produção, usar DEBUG=false, hosts explícitos e Gunicorn com
`PORT` temporária; simular o router com `X-Forwarded-Proto: https` e conferir CSS/JS
e redirect HTTP. Isso não substitui os testes HTTPS e banco no Heroku.

Checklist obrigatório de validação **no ambiente publicado**, reutilizável a cada deploy
(os campos abaixo são um modelo de registro, não o estado atual do ambiente):

- [ ] Página pública abre por HTTPS; HTTP redireciona sem loop.
- [ ] `/api/v1/health/` responde corretamente.
- [ ] CSS, JS, logos e demais static assets carregam sem 404.
- [ ] Login real do Administrador demo e Dashboard funcionam.
- [ ] Login real do Gestor limita acesso às Lojas Centro e Jardim Aurora — Araras.
- [ ] Helena entra como Cliente e acessa Início/Pontos/Resgates.
- [ ] Troca de programa não mistura Empresa, quando houver múltiplos vínculos para teste.
- [ ] OpenAPI `/api/schema/`, Swagger `/api/docs/` e ReDoc `/api/redoc/` mantêm o contrato.
- [ ] Fluxo principal autenticado da API funciona com credencial emitida pela Gestão.
- [ ] Formulários/login/logout mantêm CSRF e cookies seguros.
- [ ] `RETORNA_SEED_SENHA` foi removida; DEBUG permanece desabilitado.
- [ ] Logs do app/release após os smoke tests não têm traceback ou erro material.

Registrar os resultados de cada validação sem credenciais. Os gates locais
complementam a verificação no ambiente publicado; o Seed permanece restrito ao
provisionamento inicial em banco limpo, sem nova execução a cada deploy.

Referências oficiais: [stack Cedar heroku-26](https://devcenter.heroku.com/articles/heroku-26-stack),
[suporte a uv](https://devcenter.heroku.com/changelog-items/3238),
[build Node](https://devcenter.heroku.com/articles/nodejs-classic-buildpack-builds),
[static Django](https://devcenter.heroku.com/articles/django-assets),
[bind Gunicorn](https://gunicorn.org/reference/settings/#bind).
