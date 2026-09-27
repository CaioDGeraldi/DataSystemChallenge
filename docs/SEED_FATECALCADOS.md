# Seed FATECalçados — Retorna / F4.01

## 1. Objetivo e limites do cenário

FATECalçados é um tenant fictício para demonstrar a vertical da Retorna e preparar dados para a F4.02. Nenhuma regra específica da empresa é incorporada ao domínio geral. O comando cria o cenário uma única vez; não é ferramenta de importação, sincronização ou limpeza.

## 2. Princípios e fluxos reais utilizados

`apps/fidelidade/seed_fatecalcados.py` contém a composição executável. O comando chama os services de identidade, cadastro de Cliente, onboarding, Lojas, configuração, níveis, credencial, Evento, Compra e Resgate.

Compra gera Lote e eventual aplicação de campanha na mesma transação. Resgate gera suas alocações pelo FEFO real. O seed não cria esses fatos derivados diretamente, não altera snapshots e não desabilita autorização. Todas as escritas participam de uma transação externa; falha de qualquer etapa ou validação final reverte a carga inteira.

## 3. Pré-requisitos e ambiente de demonstração

- PostgreSQL disponível e migrations do projeto aplicadas.
- Ambiente de desenvolvimento/demonstração dedicado, com configuração habitual do Django.
- Variável `RETORNA_SEED_SENHA` definida pelo operador, contendo uma senha exclusiva de demonstração que passe pelos validadores existentes.

A senha é utilizada nas 37 contas fictícias, não é gravada em texto puro nem impressa no resumo. Não use uma senha real ou versionada. Os testes usam hasher rápido somente no ambiente de testes; o comando mantém a política normal do projeto.

O comando pode coexistir com outro tenant cujas identidades não colidam, mas a recriação oficial usa outro banco limpo. Não execute o seed como rotina de produção.

## 4. Data-base, timezone e referência temporal

`--data-base YYYY-MM-DD` é obrigatório, com formato estrito e data válida. A referência é **T = data-base às 12:00 em America/Sao_Paulo**. O cenário cobre M−15 até M, incluindo o mês da referência. Datas extremas que não comportam o histórico e a validade são recusadas.

Compras têm instantes aware, definidos pelo plano, nunca posteriores a T. Os oito Resgates ocorrem de T−8 minutos a T−1 minuto, depois das Compras que os financiam.

O relógio simulado é interno ao seed: um proxy temporário substitui apenas o binding `timezone` do módulo de Resgates. Seu instante é armazenado em `ContextVar`; outros contextos/threads usam o relógio original. Um lock reentrante protege instalações simultâneas do proxy no processo. O contexto restaura o binding e o valor mesmo em exceção.

`django.utils.timezone.now` não é modificado. API, PDV e integradores continuam sem entrada de backdating. O seed continua chamando `registrar_resgate`, sem editar o Resgate depois. Datas técnicas de criação de contas/registros continuam reais; não representam as datas de ocorrência das Compras importadas pelo cenário.

## 5. Empresa e identidades fictícias

- Nome: **FATECalçados**.
- Slug reservado: `fatecalcados`.
- CNPJ sintético: `73182649000144`.
- Administrador técnico: **Administração FATE Demonstração**, CPF sintético `73182000039`.
- 36 Clientes com CPFs determinísticos, distintos e com dígitos verificadores válidos.
- Uma credencial de integração com escopo `EMPRESA`.

Os números são sintéticos, sem intenção de representar identidades reais; validade matemática não é comprovação de inexistência de titular. Não há consulta a cadastro real nem endereço pessoal. A credencial usa geração criptográfica normal; sua chave efêmera não é impressa nem faz parte do determinismo lógico. Para uma demonstração HTTP posterior, o Administrador pode emitir outra credencial pela Gestão.

## 6. As 12 Lojas

| Cidade | Unidades fictícias | Compras por unidade |
|---|---|---:|
| Araras | Centro; Jardim Aurora; Estação | 25 |
| Limeira | Centro; Vila das Flores; Parque Sul | 25 |
| Rio Claro | Centro; Jardim Horizonte; Terminal | 25 |
| Campinas | Centro; Jardim Ipê; Parque das Águas | 25 |

Cada cidade possui três unidades. Elas permitem filtros e comparações de valor, ticket e pontos; a quantidade de Compras por Loja é deliberadamente equilibrada. A primeira Loja vem do onboarding e as outras onze do service administrativo.

## 7. Parâmetros de fidelidade

| Parâmetro | Valor |
|---|---:|
| `pontos_por_real` | 1.00 |
| `validade_pontos_meses` | 12 |
| `resgate_minimo_pontos` | 100 |
| `incremento_resgate_pontos` | 100 |
| `valor_monetario_por_ponto` | 0.05 |
| `limite_resgate_percentual` | 50.0000% |
| `precisao_pontos` | 2 |
| `modo_arredondamento_pontos` | HALF_UP |
| `periodo_cliente_ativo_dias` | 180 |

O limite de Resgate é aplicado sobre o valor bruto de futuras Compras vinculadas. A composição existente mantém seus Resgates independentes; não há vínculo ou reescrita retroativa.

Todos são salvos pelo service corporativo. Não há override de Loja. Cálculos usam `Decimal`; pontos são persistidos com quatro casas conforme o domínio.

## 8. Níveis configurados

| Nome | Pontos mínimos |
|---|---:|
| Bronze | 0.0000 |
| Prata | 1000.0000 |
| Ouro | 5000.0000 |

São dados da Empresa, criados pelo service, começando em zero. Não são enums, defaults globais ou benefícios. A classificação usa todos os pontos historicamente concedidos, inclusive os expirados e consumidos.

## 9. População de Clientes e perfis

| Grupo/códigos | Clientes | Compras | Finalidade |
|---|---:|---:|---|
| A01–A06 | 6 | 120 | Recorrentes de alto valor, 20 Compras cada, com Resgate |
| M01–M10 | 10 | 100 | Recorrentes médios, 10 Compras cada |
| B01–B08 | 8 | 48 | Baixa frequência, 6 Compras cada |
| U01–U06 | 6 | 6 | Uma Compra por Cliente |
| I01–I06 | 6 | 26 | Inativos: dois com 5 Compras e quatro com 4 |
| **Total** | **36** | **300** | |

Os tickets variam de R$ 69,90 a R$ 1.100,00. O ticket alto de Helena representa Compras familiares. Valores e distribuição são explícitos; não há população gerada por sorteio. A variedade é entre perfis; vários Clientes têm ticket constante para facilitar a explicação.

## 10. Personagens da demonstração

Resultados esperados para **2026-09-24**, derivados da composição fixa e dos cálculos de domínio. A execução emite os valores efetivamente persistidos e classificados no resumo JSON; a suíte verifica os resultados abaixo. Esta documentação não representa uma execução de testes.

| Personagem | Código | Pontos históricos | Nível | Saldo em T | Resgate | Papel |
|---|---|---:|---|---:|---:|---|
| Marina Valença | A01 | 6.600,00 | Ouro | 4.000,00 | 2.000 | Nível não cai ao consumir saldo |
| Otávio Cedro | B01 | 419,40 | Bronze | 279,60 | — | Lote próximo de expirar |
| Helena Fontoura | I01 | 5.500,00 | Ouro | 3.300,00 | — | Ouro e inativa; histórico expirado continua contando |
| Ravi Monteiro | M01 | 2.219,10 | Prata | 1.659,30 | 200 | Compra de R$ 300 gera 600 pontos na campanha |
| Lia Nogueira | U01 | 149,90 | Bronze | 149,90 | — | Compra única recente |
| Bento Amaral | M02 | 1.409,10 | Prata | 1.029,30 | 200 | Consumo FEFO atravessa três Lotes |

Para essa referência, Helena comprou pela última vez em 01/01/2026. Otávio possui Lote que expira em 01/10/2026. Bento consome 89,90 + 89,90 + 20,20 pontos, sem alteração dos Lotes. O resumo também lista os outros 30 Clientes.

## 11. Compras e distribuição temporal

| Faixa | Quantidade |
|---|---:|
| M−15 a M−12 | 60 |
| M−11 a M−8 | 80 |
| M−7 a M−4 | 80 |
| M−3 a M | 80 |

Nenhum mês fica vazio. O planejador reserva as Compras narrativas e preenche as quotas restantes em ordem estável, equilibrando os meses de cada faixa. Segundos distintos evitam empates incidentais de FEFO entre Compras do cenário. A ordem de inserção é cronológica, com identificador como desempate.

Para setembro/2026, a distribuição mensal é: junho–setembro/2025, 15 por mês; outubro/2025–maio/2026, 20 por mês; junho e julho/2026, 13 cada; agosto, 24; setembro, 30. Outras datas-base podem redistribuir os meses dentro das mesmas quatro quotas.

Identificadores `FATE-DEMO-V1-C001` até `C300` são estáveis e representam slots, não PKs nem uma enumeração cronológica.

## 12. Campanha 2x e proveniência histórica

**Semana de passos em dobro** tem escopo Empresa, início no dia T−45 às 00:00 e fim no dia T−38 às 23:59:59, ambos no timezone local. Há um efeito `MULTIPLICADOR_PONTOS = 2.0000`.

São 24 Compras atingidas: duas por Cliente A, uma por Cliente M e uma para B02 e B03. As demais Compras são agendadas fora do intervalo. O motor real gera as 24 aplicações históricas; o seed não altera `pontos_concedidos`.

A campanha não é cancelada. O estado exibido na Gestão depende da hora real no momento da consulta; a resolução das Compras usa sua ocorrência histórica.

## 13. Pontos, validade e expiração

Os 300 Lotes vêm das 300 Compras e usam validade de **12 meses de calendário**, pelo cálculo oficial; não se somam 365 dias. Existem Lotes expirados, válidos por vários meses e um caso de Otávio que vence em até 14 dias após T.

Não se escreve `expira_em` manualmente. Na referência de 24/09/2026, há 15.628,00 pontos concedidos em Lotes já expirados. Expiração não remove pontos da classificação histórica.

## 14. Resgates, descontos e consumo FEFO

| Clientes | Pontos por Resgate | Quantidade | Desconto total |
|---|---:|---:|---:|
| Marina / A01 | 2.000 | 1 | R$ 100,00 |
| A02–A06 | 500 | 5 | R$ 125,00 |
| Ravi e Bento / M01–M02 | 200 | 2 | R$ 20,00 |
| **Total** | **4.900** | **8** | **R$ 245,00** |

Os identificadores são `FATE-DEMO-V1-R01` até `R08`. O service mantém advisory lock idempotente, lock do Cliente, locks dos Lotes, elegibilidade estrita e ordem `expira_em → adquiridos_em → pk`. A soma de alocações precisa completar cada Resgate sem exceder concessões.

Para 24/09/2026, são esperadas 22 alocações. A quantidade é resultado do FEFO, não uma quantidade fabricada pelo seed.

## 15. Nível, saldo e atividade

- **Nível:** obtido por `classificar_cliente`, somando concessões históricas.
- **Saldo em T:** soma do restante dos Lotes com `expira_em > T`, descontadas suas alocações.
- **Disposição de atividade:** 30 Clientes com Compra recente e 6 com última Compra bem anterior a T−180 dias.

O resumo usa `compra_na_janela_180d` como evidência temporal do cenário, não como novo atributo ou motor de atividade do produto. Não há Compra na fronteira de 180 dias; a definição final do indicador pertence à F4.02. Nem saldo, nível ou atividade são materializados no Cliente.

## 16. Composição quantitativa e resultados esperados

| Item | Resultado |
|---|---:|
| Empresas / Lojas / Administradores | 1 / 12 / 1 |
| Credenciais / Clientes | 1 / 36 |
| Compras / Lotes | 300 / 300 |
| Eventos / aplicações 2x | 1 / 24 |
| Resgates | 8 |
| Clientes Bronze / Prata / Ouro | 14 / 15 / 7 |
| Valor total das Compras | R$ 82.337,80 |
| Pontos concedidos históricos | 89.187,60 |
| Pontos resgatados | 4.900,00 |
| Descontos registrados | R$ 245,00 |

Para **24/09/2026**, o saldo total esperado em T é 68.659,60 pontos e são esperadas 22 alocações. Saldos e vencimentos devem ser interpretados na referência declarada, não no dia de leitura do documento. O JSON final deriva dos registros persistidos e não grava indicadores em tabelas de Dashboard.

## 17. Como executar

Com PostgreSQL disponível, carregue a configuração local e aplique as migrations conforme o fluxo habitual do projeto:

```bash
set -a
. ./.env.datasystem
set +a
uv run python manage.py migrate
```

No Bash, leia uma senha de demonstração sem gravá-la no histórico do shell:

```bash
read -rs -p 'Senha exclusiva de demonstração: ' RETORNA_SEED_SENHA
export RETORNA_SEED_SENHA
uv run python manage.py seed_fatecalcados --data-base 2026-09-24
unset RETORNA_SEED_SENHA
```

Ao concluir o commit, o comando imprime um JSON com quantidades, referência, CPF administrativo e classificação/saldo dos Clientes. A senha e a chave de integração não aparecem. Para acessar Gestão, use o CPF administrativo e a senha fornecida. Erros abortam a carga; nenhum resumo de sucesso é impresso antes da conclusão.

Validação local da feature:

```bash
uv run python manage.py test apps.fidelidade.test_seed_fatecalcados
uv run python manage.py test
```

## 18. Reexecução e recriação segura

Antes da primeira escrita, o comando procura Empresa com CNPJ, slug ou nome reservado; qualquer CPF das 37 contas; e identificadores de Compra/Resgate com o prefixo reservado, inclusive em outro tenant. Encontrar qualquer um deles aborta claramente, sem reutilizar ou atualizar o cenário.

Um `pg_advisory_xact_lock`, com chave SHA-256 fixa do seed V1, serializa duas execuções do comando. As pré-checagens são repetidas sob esse lock antes de escrever. Uma identidade surgida por outro fluxo durante a carga só é aceita se o próprio cadastro do seed a criou; uma observação temporária de `post_save`, restrita à thread e CPF, detecta reutilização e provoca rollback. O receptor é desconectado em sucesso e falha.

Não existem `--reset`, `--force-delete`, `TRUNCATE` ou remoção de históricos. Para recriar:

1. Provisione **outro banco de demonstração limpo**, preservando o anterior.
2. Aponte a configuração local para esse banco.
3. Execute `migrate`.
4. Execute o seed com a data-base desejada.

Uma falha transacional não deixa o cenário parcial e permite tentar novamente. Sequências do PostgreSQL podem avançar mesmo após rollback; PKs não fazem parte da identidade lógica.

## 19. Garantias e limites de determinismo

Mesma data-base e mesma versão da composição produzem as mesmas identidades narrativas, Compras, concessões, campanhas, Resgates, alocações e resultados na referência. O plano não usa sorteio ou a hora real. A carga usa contexto Decimal próprio.

Ficam fora da igualdade lógica: PKs, salts/hashes de senha, segredo e identificador aleatório da credencial, timestamps técnicos de criação. A senha fornecida não muda o cenário financeiro. O relógio simulado não governa sessões, autenticação ou a aplicação inteira.

Outro dia de execução não muda os fatos narrativos; outro dia de **consulta**, com a aplicação no relógio real, pode mudar validade de saldo e estado de campanha. Não há congelamento permanente da aplicação.

## 20. Indicadores preparados para a F4.02

O conjunto permite calcular quantidade de Clientes, ticket médio, descontos, evolução mensal, pontos históricos, resgatados e disponíveis, distribuição por nível, Compras recentes e futura recompra. As Lojas permitem filtros por unidade/cidade.

A F4.01 não implementa nem persiste indicadores. A futura F4.02 deve explicitar janela, referência temporal e definição de cada métrica, especialmente atividade e recompra.

## 21. Limitações e funcionalidades fora de escopo

Não há Dashboard, seed de infraestrutura, deploy, benefícios por nível, bônus por nível, estorno, cancelamento de Resgate, área do Cliente enriquecida, API pública de saldo/níveis ou regra FATECalçados no domínio geral. O cenário é pequeno, deliberadamente explicável e não representa uma amostra estatística de mercado.

Os testes escritos cobrem calendário, composição, services reais, FEFO, personagens, determinismo lógico por cargas revertidas em estados limpos equivalentes, colisões, preservação de outro tenant, rollback e concorrência PostgreSQL. A execução local desses testes é necessária antes de afirmar resultados de validação.
