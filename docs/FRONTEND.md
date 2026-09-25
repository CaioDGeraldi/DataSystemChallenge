# Frontend da Retorna

## Arquitetura

A Retorna usa Django server-rendered com frontend isolado em `frontend/`. A referência arquitetural e visual é a fundação local de FractawModules, documentada no ADR 0021 daquele projeto: Gentelella v4 seletivo, shell fluido, rail desktop e drawer mobile. A identidade, as rotas, o tenant e a autorização pertencem à Retorna.

Não há SPA nem servidor HTTP frontend separado. Vite apenas compila os assets; Django renderiza e serve a aplicação.

## Dependências e estrutura

Node >=22.12.0, Gentelella **4.2.0**, Sass **1.104.1** e Vite **8.3.0**, com versões diretas exatas e `package-lock.json` versionado.

```text
frontend/
├── package.json / package-lock.json / vite.config.js
├── licenses/GENTELELLA-LICENSE.txt
├── src/
│   ├── styles/
│   │   ├── retorna.scss
│   │   ├── retorna/{_tokens,_base,_shell,_components}.scss
│   │   └── vendor/_gentelella.scss
│   └── js/
│       ├── retorna.js
│       ├── integrations/gentelella/shell.js
│       └── retorna/{appearance,campaign-scope,composed-form,integracao-form,invite-share,sidebar-sections,user-menu}.js
└── dist/                         # gerado, não versionado
    ├── retorna.css
    └── retorna.js
```

`vendor/_gentelella.scss` concentra os imports de tokens, layout, componentes e forms v4. Não se importa o entrypoint JS do vendor, demos, gráficos, command palette ou service worker. Dependências transitivas de demonstração podem existir no node_modules, mas não são importadas no entrypoint da Retorna. A licença MIT está preservada em `frontend/licenses/`.

## Instalação e build

Na raiz do repositório:

```sh
cd frontend
npm ci
npm run build
```

O build gera nomes estáveis `retorna.css` e `retorna.js`, sem sourcemaps. `frontend/dist/` e node_modules são ignorados. Faça o build antes dos testes Django que verificam assets e antes de collectstatic. Não editar bundles manualmente nem restaurar o pipeline Sass CLI da raiz.

## Desenvolvimento com dois terminais

Terminal 1:

```sh
cd frontend
npm run dev
```

O script executa `vite build --watch --mode development`: observa fontes e recompila bundles, sem abrir dev server Vite. Recarregue o navegador após a compilação.

Terminal 2, com o ambiente Django configurado:

```sh
uv run python manage.py runserver
```

## Staticfiles e marca

Django encontra os bundles em `frontend/dist/`. O namespace `retorna/brand` aponta diretamente para `assets/retorna/`, preservando os SVGs originais sem duplicação. `STATIC_ROOT` é `staticfiles/`, saída gerada para collectstatic. Configuração de servidor de produção fica fora desta entrega.

Navy `#0D1426`, verde `#5EC33D` como acento e branco permanecem próprios da Retorna. Logo dark na sidebar navy; logo light na base pública; icon no favicon e no rail. Tipografia system-ui. Tokens semânticos mapeiam a paleta às primitivas Gentelella e sustentam os temas Automático, Claro e Escuro, além das preferências locais de escala de texto e modo dos formulários.

## Templates e navegação

O namespace `datasystem` foi preservado. `base.html` é a base pública; `gestao_base.html` especializa a estrutura empresarial com sidebar, topbar, backdrop e main/page-wrapper/footer. Includes concentram navegação, topbar, retorno, mensagens e campos de formulário.

As views fornecem apresentação a partir do membro já validado. Administrador recebe seis entradas reais; Gestor somente Lojas permitidas. Cliente, cadastro e aceite público não recebem shell empresarial. O menu da identidade contém apenas logout POST com CSRF.

Breadcrumbs são dados server-side: ancestrais navegáveis possuem URL; o item atual é texto com aria-current. Configuração de Loja usa `Lojas / Configuração — <nome>` e `Voltar para Lojas`, sem página de detalhe fictícia. Telas filhas possuem back_url/back_label determinísticos.

## Geometria e comportamento

A área de Gestão é fluida, com offsets do vendor e gutters comuns de page-wrapper, sem max-width global. Sidebar expandida de 252px, rail de 64px, topbar de 56px. Até 768px, drawer com backdrop, Escape, contenção básica de foco e retorno ao toggle; tabelas têm apresentação desktop e cards até 600px. Formulários e listagens compartilham densidade compacta, raios de 4/6/8px, bordas e sombras discretas.

JavaScript controla somente apresentação: rail/drawer, seções recolhíveis e dropdown. Rail e seções não são persistidos; as preferências visuais são locais ao navegador. A autorização e a composição dos links são server-side. O comportamento existente de seleção de Lojas no formulário de integração está no entrypoint compartilhado e só inicializa quando seus campos existem.

## Validação

### Formulários compostos e ilustração

Formulários de dados usam um único renderer e, quando houver dois ou mais grupos,
fieldsets com etapas. O agrupamento é apresentação (`FormularioCompostoMixin`):
onboarding (Empresa, Primeira Loja, Administrador), configuração corporativa
(Acúmulo, Validade e atividade, Resgate), convite (Pessoa, Acesso), Campanha
(Campanha, Aplicação, Pontuação), chave (Identificação, Acesso), cadastro de Cliente
e aceite de convite para nova identidade (Identificação, Acesso).
Grupos cujos campos foram removidos pelo fluxo existente não são renderizados.

Loja, Nível, configuração específica, login e seleção de contexto permanecem
simples. Aceite autenticado continua uma ação; aceite de identidade existente
mantém somente a senha. Logout e ações destrutivas não recebem etapas.

Sem JS, fieldsets e submit permanecem visíveis. Com JS, o modo inicial segue a preferência local (padrão: etapas);
Anterior/Próximo validam e movimentam o foco. Exibir tudo preserva os mesmos
controles e valores. Erros retornados pelo servidor marcam as etapas e focam o
resumo. O toggle individual não altera a preferência global. Não há novo bloqueio de processamento.

Ilustrações só aparecem quando ajudam a explicar a superfície. Atualmente somente
onboarding inicial usa Onboarding/Bro, Storyset / Freepik. Configuração, Campanha,
convite, chave, Loja, Nível, login, cadastro e aceite não têm ilustração. Os forms
operacionais usam uma coluna centralizada, com limite de 800px da própria superfície,
sem limitar globalmente o shell. Etapas, campos, erros e ações permanecem iguais.

As variantes `frontend/public/illustrations/welcome_onboarding-light.svg` e
`welcome_onboarding-dark.svg` são copiadas pelo Vite para `dist/illustrations/`.
O include usa `<img alt="">` dentro de figura decorativa e URLs `{% static %}`.
CSS seleciona a variante pelo tema: verde Retorna comum, traços claros no dark,
fundo transparente, sem inversão. No desktop fica lateral; até 1100px fica abaixo;
até 768px fica oculta. Crédito no footer do onboarding e origem/termos em
`frontend/licenses/STORYSET.md`. O antigo Forms foi removido, inclusive do catálogo local.

Os contratos de templates, breadcrumbs, retorno, papéis, CSRF e staticfiles estão em `apps.empresas.test_interface`. A equipe deve executar o build antes dos testes.

Revisar manualmente desktop expandido/rail e mobile: alinhamento, teclado, Escape, foco ao fechar/abrir, resize, seções recolhidas, menu da identidade, campos inválidos, tabelas largas e chaves longas. Testes server-side não comprovam comportamento JS nem aparência visual.

## Aparência e acessibilidade

O menu de identidade e o header público oferecem um diálogo nativo de preferências:
Automático/Claro/Escuro, texto 100/110/120% e formulários Em etapas/Exibir tudo.
Escape fecha; o foco retorna ao acionador. Não há rota, model ou estado no servidor.

A chave `retorna.interface.v1` guarda somente JSON
`{"theme":"system","fontScale":100,"formMode":"steps"}` após interação explícita.
Valores são validados e propriedades desconhecidas descartadas. Falhas de leitura
ou escrita não bloqueiam a interface; o painel avisa quando não consegue salvar.
Restaurar padrão reaplica esses três valores.

Um bootstrap pequeno antes do CSS aplica atributos no `html` para evitar flash.
Automático acompanha `prefers-color-scheme` em runtime. Tema explícito prevalece.
A escala usa font-size raiz, sem zoom/transform. Tokens semânticos definem os dois
temas; a ilustração do onboarding tem variantes locais e superfície transparente, sem inversão.

O modo global afeta a abertura dos próximos formulários. Um atributo específico
`data-composed-form-initial-mode` válido, se necessário, tem precedência; os forms
atuais não o fixam. Sem JS, tema claro, campos e submit permanecem disponíveis,
assim como navegação e logout. Os controles de preferências não são expostos.

Foco, reduced motion e forced-colors são tratados globalmente. A validação Node
`node frontend/scripts/validate-interface.mjs` cobre preferências, bootstrap,
fallback e contraste de pares principais de tokens; não substitui revisão visual
ou testes com tecnologia assistiva. Execute também `cd frontend && npm run build`.

## Páginas públicas

`/` é client-first: apresenta pontos e recompensas para quem participa de programas,
com Entrar como ação principal. Inclui Compre/Acumule/Aproveite, conceitos de pontos,
campanhas, níveis e recompensas e um link secundário para `/para-empresas/`.
Não cria páginas de pontos, histórico ou resgates nem promete benefícios automáticos.

`/para-empresas/` explica o produto em linguagem de negócio: para quem é, o problema
de regras espalhadas, como funciona, seis recursos e conexão com os sistemas da
empresa. Criar empresa e Entrar usam onboarding/login existentes. Não há Dashboard,
formulário comercial ou destino fictício. Ambas ficam sem ilustração: o catálogo
local não oferece uma figura que melhore essas mensagens sem forçar seu significado.

Para autenticados, `/` mantém os contextos de `resolver_contextos`, inclusive quando
há somente um, sem redirecionar. A escolha usa CSRF e o fluxo `/contextos/`. Com
contexto ativo, oferece continuidade e informa a restrição existente de troca.
Sem vínculos, mostra estado vazio e onboarding. Essa lógica não mudou nesta rodada.

Header público: marca/Home, Para empresas, Entrar quando deslogado e preferências.
Logout continua POST para autenticados. Footer inclui Para empresas e crédito
Storyset na superfície ilustrada. Layouts usam tokens dos dois temas, cards fluidos,
ações com alvo mínimo de 44px e quebra para telas estreitas. Revisar manualmente
390/600/768/1024/1440px, incluindo escala de texto 120%.
