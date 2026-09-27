# FATECalçados — cenário de demonstração V2 (F4.01B / #72)

O seed prepara uma Empresa fictícia para demonstrar a vertical integrada após F3.06. Usa PostgreSQL e os services reais de identidade, onboarding, convite/aceite, configuração, níveis, Clientes, credencial, campanha, Compra, Resgate e Estorno. Não introduz regras FATECalçados no domínio geral nem implementa o Dashboard #65.

## Contas de demonstração

**A conta principal da apresentação é o Administrador.** Ela autentica pelo fluxo normal, abre o contexto de Gestão e possui acesso corporativo implícito às 12 Lojas. O seed cria exatamente um `MembroEmpresa/ADMINISTRADOR`; não cria outro dono ou superusuário. A validação final exige identidade, papel, vínculo ativo, autenticação e contexto utilizável, além do escopo completo.

| Prioridade | Identidade | CPF reservado | Papel e finalidade |
|---|---|---|---|
| 1 | Administração FATE Demonstração | `73182000039` | ADMINISTRADOR; apresentação da Gestão e acesso às 12 Lojas; pronto para o futuro Dashboard |
| 2 | Alex Caminho | `73182009095` | GESTOR; apenas Centro — Araras e Jardim Aurora — Araras |
| 3 | I01 — Helena Fontoura | `73182003135` | Cliente; consulta, simulação e Compra de retorno ao vivo |

O Gestor tem exatamente dois `AcessoLoja`, gerados por convite e aceite oficiais. As outras dez Lojas não aparecem em seu escopo. O Administrador não precisa de `AcessoLoja` explícito.

São 38 identidades: Administrador, Gestor e 36 Clientes. Os CPFs são sintéticos, determinísticos e matematicamente válidos, sem intenção de representar titulares reais. Todas usam a senha recebida exclusivamente em runtime por `RETORNA_SEED_SENHA`. Somente os hashes normais de autenticação são persistidos; nenhuma senha bruta entra no código, documento ou resumo.

Empresa: **FATECalçados**; slug `fatecalcados`; CNPJ sintético `73182649000144`.

## Execução

Aponte a configuração para um banco PostgreSQL de demonstração e aplique as migrations pelo fluxo habitual:

```bash
set -a
. ./.env.datasystem
set +a
uv run python manage.py migrate
```

No Bash, leia a senha sem registrá-la no histórico nem exibi-la:

```bash
read -rs -p 'Senha exclusiva de demonstração: ' RETORNA_SEED_SENHA
export RETORNA_SEED_SENHA
```

Opcionalmente, configure um arquivo operacional em um diretório privado já existente, **fora do repositório**, para receber a credencial utilizável pelo PDV/Swagger:

```bash
export RETORNA_SEED_CREDENCIAL_ARQUIVO=/diretorio-privado/fate-integracao.key
uv run python manage.py seed_fatecalcados --data-base 2026-09-24
unset RETORNA_SEED_SENHA RETORNA_SEED_CREDENCIAL_ARQUIVO
```

Sem `RETORNA_SEED_CREDENCIAL_ARQUIVO`, a credencial continua sendo criada pelo service oficial, mas a chave bruta é descartada, sem outro canal automático de exposição. O operador pode emitir uma nova credencial pela Gestão posteriormente.

`--data-base` é obrigatório, estritamente `YYYY-MM-DD`. A referência T é meio-dia em `America/Sao_Paulo`. Para a apresentação ao vivo, escolha uma data-base próxima da execução: consultas HTTP usam o relógio real, sem congelamento permanente.

O comando imprime somente o resumo JSON após a conclusão da transação. O Administrador entra com seu CPF e a senha fornecida para abrir a Gestão.

## Credencial operacional e rollback

`criar_credencial` mantém seu contrato: identificador e segredo aleatórios, retorno efêmero da chave completa e persistência apenas do hash do segredo. O seed não fixa nem altera esses valores.

Quando configurado, o arquivo recebe a chave completa uma única vez, com criação exclusiva (`O_EXCL`) e permissão `0600`, inclusive sob umask restritiva. Arquivo ou symlink preexistente é recusado, sem sobrescrita ou remoção. A chave não aparece em stdout, stderr, logs ou resumo; o JSON pode conter apenas `credencial_arquivo`, com o caminho configurado.

A escrita, flush e sincronização do arquivo ocorrem dentro da carga transacional. Falha de criação/escrita aborta a carga. Se uma falha posterior, inclusive de commit, acontecer, o seed desfaz o banco e remove somente o arquivo identificado como criado por esta execução. Um arquivo substituído por outro inode não é removido. Com arquivo habilitado, a carga exige uma transação externa própria, para que seu retorno corresponda ao commit.

Filesystem e PostgreSQL não compartilham transação distribuída: encerramento abrupto do processo ou queda da máquina pode deixar arquivo operacional órfão. Falha de remoção é reportada sem expor a chave. Mantenha o diretório privado e verifique o resultado da operação antes de usar a credencial.

## Configuração corporativa V2

| Parâmetro | Valor |
|---|---|
| `pontos_por_real` | 1.00 |
| `validade_pontos_meses` | 12 meses de calendário |
| `resgate_minimo_pontos` / `incremento_resgate_pontos` | 100 / 100 |
| `valor_monetario_por_ponto` | 0.05 |
| `precisao_pontos` / `modo_arredondamento_pontos` | 2 / HALF_UP |
| `periodo_cliente_ativo_dias` | 180 |
| `modo_aplicacao_nivel` | ATINGIDO_NA_COMPRA |
| `inatividade_suspende_beneficios_nivel` | true |
| `beneficio_primeira_compra_apos_inatividade` | COM_BENEFICIOS_NIVEL |
| `promocao_retorno_ativa` | true |
| `bonus_pontos_retorno_percentual` | 15% |
| `desconto_retorno_percentual` | 10% |
| `modo_combinacao_descontos_percentuais` | ADITIVO |
| `ordem_aplicacao_resgate` | DEPOIS_DOS_DESCONTOS_PERCENTUAIS |
| `limite_resgate_percentual` | 50% |
| `devolver_pontos_ao_estornar_resgate` | true |

Há exatamente **um override de Loja**, criado por `salvar_override_loja` no contexto do Administrador antes das Compras: **Jardim Aurora — Araras, `pontos_por_real = 2.00`**. Centro — Araras não possui override e herda `1.00` da Empresa; as outras dez Lojas também herdam `1.00`. Nenhum outro parâmetro recebe override.

O Gestor continua restrito a Centro e Jardim Aurora, permitindo comparar herança e configuração efetiva. Criar/editar override continua sendo uma operação autorizada somente ao Administrador.

Campos não exigidos pela Issue preservam os defaults existentes: por exemplo, `base_calculo_pontos = BRUTO`. O limite de Resgate usa a composição oficial; os oito Resgates históricos do cenário continuam independentes, sem vínculo retroativo com Compras.

| Nível | Threshold | Bônus de pontos | Desconto |
|---|---:|---:|---:|
| Bronze | 0 | 0% | 0% |
| Prata | 1000 | 10% | 5% |
| Ouro | 5000 | 20% | 10% |

Os níveis são dados deste tenant. A classificação usa concessões históricas, incluindo pontos expirados e consumidos. `ATINGIDO_NA_COMPRA` orienta o nível do bônus conforme o domínio existente; descontos continuam usando o nível anterior. Campanha, bônus de nível e retorno são compostos pelo motor, sem multiplicar artificialmente os bônus pelo multiplicador da campanha.

## Helena: estado inicial da demonstração ao vivo

**O seed termina com Helena inativa e sem persistir sua Compra de retorno.** Ela tem cinco Compras antigas, nível Ouro preservado, 6.160 pontos históricos e saldo de 3.740 pontos em T na referência de 24/09/2026. Sua última Compra é de 01/01/2026; expiração de Lotes não reduz o nível histórico.

Na consulta, `beneficios.aplicaveis` significa **elegibilidade dos benefícios para a próxima Compra avaliada naquele instante**. Não significa usufruir benefícios fora de uma Compra. Com `COM_BENEFICIOS_NIVEL`, Helena inativa corretamente apresenta benefícios elegíveis e promoção de retorno aplicável. Não se descreve esse estado como “benefícios suspensos antes da Compra”. A configuração corporativa de suspensão permanece `true`, com a exceção de retorno já definida pelo contrato.

Roteiro da persona secundária:

1. Consultar `GET /api/v1/clientes/fidelidade/` com uma Loja autorizada e CPF de Helena.
2. Mostrar inatividade, Ouro histórico, benefícios elegíveis e promoção de retorno aplicável.
3. Simular `POST /api/v1/compras/simular/` com valor de R$ 300,00 em Centro — Araras.
4. Na referência T, fora da campanha histórica, mostrar 405 pontos estimados: 300 base + 60 de nível + 45 de retorno; valor final R$ 240,00, com descontos aditivos de 10% + 10%.
5. Registrar a Compra real pelo contrato normal `POST /api/v1/compras/` e consultar novamente: Helena torna-se ativa.

Uma Compra equivalente de Helena em Jardim Aurora — Araras usa 2.00 pontos por real e gera 810 pontos (600 base + 120 de nível + 90 de retorno), com o mesmo valor bruto de R$ 300,00 e valor final de R$ 240,00. Os testes realizam consulta, simulação e registro real em isolamento transacional. Essa Compra adicional nunca integra as 303 Compras persistidas pelo seed.

## Lojas e população

| Cidade | Unidades | Compras por unidade |
|---|---|---|
| Araras | Centro; Jardim Aurora; Estação | 26; 26; 26 |
| Limeira | Centro; Vila das Flores; Parque Sul | 25; 25; 25 |
| Rio Claro | Centro; Jardim Horizonte; Terminal | 25; 25; 25 |
| Campinas | Centro; Jardim Ipê; Parque das Águas | 25; 25; 25 |

A primeira Loja vem do onboarding; as outras onze, do service administrativo.

| Grupo | Clientes | Compras finais | Finalidade |
|---|---:|---:|---|
| A01–A06 | 6 | 120 | Recorrentes de alto valor e Resgates |
| M01–M10 | 10 | 100 | Recorrentes médios; FEFO e Estorno |
| B01–B08 | 8 | 48 | Bronze/Prata e expiração próxima |
| U01–U06 | 6 | 7 | Compra recente; Lia com retorno Bronze |
| I01–I06 | 6 | 28 | Histórico antigo; Helena preservada inativa; Mauro/Rosa com retorno realizado |
| Total | 36 | 303 | 32 ativos e 4 inativos em T |

Os códigos são identidades narrativas estáveis, não classificação automática de atividade: I02 e I03 ficam ativos na V2. I01, I04, I05 e I06 permanecem inativos.

## Fatos adicionais e personagens históricos

As 300 Compras originais permanecem como fatos de entrada. A V2 adiciona exatamente três, processadas em ordem cronológica junto às demais:

| Identificador | Personagem | Momento | Finalidade |
|---|---|---|---|
| `FATE-DEMO-V1-C301` | U01 — Lia Nogueira | M−14, dia 15 | Histórico anterior à Compra recente; esta passa a ser retorno Bronze |
| `FATE-DEMO-V1-C302` | I02 — Mauro Limoeiro | T−42, durante campanha | Retorno Prata + campanha |
| `FATE-DEMO-V1-C303` | I03 — Rosa Horizonte | T−4 | Retorno Prata sem campanha |

O prefixo reservado V1 é preservado por compatibilidade de identificação e proteção one-shot; não significa manter os resultados financeiros V1. Com a nova configuração, todos os resultados são novamente produzidos pelo domínio durante a carga inicial.

- **Lia:** Compra recente de R$ 149,90 gera 172,39 pontos com retorno de 15%, sem bônus Bronze; valor final R$ 134,91.
- **Mauro:** Compra de retorno de R$ 300,00 em Jardim Aurora gera 1.350 pontos: 600 pontos base × campanha 2 + 60 de Prata + 90 de retorno; valor final R$ 255,00.
- **Rosa:** Compra de retorno de R$ 300,00 gera 375 pontos: 300 base + 30 de Prata + 45 de retorno; valor final R$ 255,00.
- **Marina / A01:** Ouro e Resgate de 2.000 pontos; consumo não reduz nível histórico.
- **Otávio / B01:** Lote próximo de expirar, em até 14 dias após T (01/10/2026 para a referência documentada).
- **Bento / M02:** Resgate de 200 pontos atravessa três Lotes em FEFO.
- **Ravi / M01:** Resgate de 200 pontos seguido de Estorno integral, preservando Resgate, alocações e Lotes.

A campanha **Semana de passos em dobro** vai de T−45 às 00:00 a T−38 às 23:59:59, com escopo Empresa e `MULTIPLICADOR_PONTOS = 2.0000`. São 25 Compras atingidas: as 24 originais e o retorno de Mauro. As demais ocorrem fora da campanha.

## Histórico, Resgates e Estorno

Há Compras em todos os 16 meses de M−15 até M. As quotas finais por faixa são **61 / 80 / 80 / 82**, respectivamente M−15 a M−12, M−11 a M−8, M−7 a M−4 e M−3 a M. Os três acréscimos têm finalidade narrativa explícita; as distribuições mensais podem variar conforme a data-base.

As Compras geram 303 Lotes pelo service, com validade oficial de 12 meses de calendário. Não há edição manual de snapshots, pontos, saldo, nível, descontos ou vencimentos.

Os oito Resgates, `FATE-DEMO-V1-R01` a `R08`, ocorrem entre T−8 e T−1 minutos: A01 resgata 2.000 pontos; A02–A06, 500 cada; M01 e M02, 200 cada. O domínio aplica FEFO (`expira_em → adquiridos_em → pk`), excluindo Lotes expirados.

`FATE-DEMO-V1-E01` estorna R07, de Ravi, em T−30 segundos. Devolve 200 pontos ao saldo elegível e preserva integralmente os fatos originais. São sete Resgates efetivos após esse Estorno.

O relógio de demonstração é um proxy restrito ao binding do módulo usado para Resgate, Estorno ou consulta interna. `ContextVar` isola o instante por contexto, com fallback real nos demais; um lock reentrante serializa instalações. O binding é restaurado mesmo em erro. `django.utils.timezone.now`, timestamps técnicos e os contratos públicos não são alterados; não há nova entrada de backdating na API.

## Números verificados para 2026-09-24

| Indicador | Resultado |
|---|---:|
| Empresas / Lojas | 1 / 12 |
| Overrides de Loja | 1 (Jardim Aurora — Araras, 2.00) |
| Administradores / Gestores / AcessoLoja do Gestor | 1 / 1 / 2 |
| Identidades / Clientes / credenciais | 38 / 36 / 1 |
| Compras / Lotes | 303 / 303 |
| Campanhas / aplicações históricas | 1 / 25 |
| Resgates / alocações / Estornos | 8 / 22 / 1 |
| Resgates efetivos | 7 |
| Clientes ativos / inativos | 32 / 4 |
| Bronze / Prata / Ouro | 14 / 15 / 7 |
| Valor bruto das Compras | R$ 83.087,70 |
| Valor final das Compras após benefícios | R$ 79.543,01 |
| Pontos concedidos históricos | 107.961,83 |
| Pontos resgatados históricos | 4.900 |
| Pontos devolvidos pelo Estorno | 200 |
| Descontos históricos de Resgate | R$ 245,00 |
| Descontos de Resgates efetivos | R$ 235,00 |
| Concessões em Lotes expirados | 17.737,90 |
| Saldo disponível em T | 85.523,93 |

Em relação à V2 anterior ao override, os pontos históricos passam de 97.939,93 para 107.961,83 (**+10.021,90**), o saldo em T de 77.242,03 para 85.523,93 (**+8.281,90**) e as concessões em Lotes expirados de 15.997,90 para 17.737,90 (**+1.740,00**). A distribuição permanece 14 Bronze / 15 Prata / 7 Ouro, assim como as quantidades de fatos e o valor bruto de R$ 83.087,70. As 26 Compras de Jardim Aurora recebem a taxa efetiva 2.00 pelo motor real, sem alterar os valores ou a agenda das Compras. Os demais benefícios podem refletir o progresso histórico maior.

O resumo deriva dos registros persistidos: inclui totais históricos, saldo líquido do consumo efetivo, atividade, níveis, Estorno, valor bruto e valor final das Compras. `descontos` mantém a soma histórica dos Resgates; `descontos_resgates_efetivos` desconta o Estorno. Não confundir esses valores com descontos de nível/retorno das Compras.

A distribuição por Loja, o histórico mensal, os snapshots de benefícios, o consumo e o Estorno fornecem dados coerentes para o Dashboard #65. Nenhum indicador é materializado em tabelas de Dashboard.

## One-shot, integridade e determinismo

O seed recusa Empresa/CNPJ/slug/nome, qualquer um dos 38 CPFs e prefixos de operações reservados já existentes, inclusive em outro tenant. A arbitragem PostgreSQL usa o mesmo advisory lock da V1 e repete a pré-checagem antes de escrever. Identidades surgidas em corrida não são reutilizadas: o seed verifica a criação pelo fluxo oficial.

Não existem reset, TRUNCATE, exclusão de históricos ou atualização da instalação V1. Para outro cenário, provisione outro banco de demonstração limpo. Uma falha transacional reverte a carga; sequências podem avançar, sem afetar identidade lógica.

Mesma data-base e mesma versão do cenário produzem os mesmos fatos, benefícios, classificações, saldos, Resgates, Estorno e alocações. PKs, hashes/salts, tokens de convite, identificador/segredo da credencial e timestamps técnicos ficam fora da igualdade lógica. O contexto Decimal é próprio. Outra data de consulta pode mudar atividade e expiração, pois a aplicação usa tempo real.

## Testes focados

```bash
uv run python manage.py test apps.fidelidade.test_seed_fatecalcados
```

Os testes cobrem planejamento/calendário, autenticação e Gestão, autorização do Gestor, override exclusivo e herança Empresa → Loja, Compras equivalentes nas duas Lojas, configuração, benefícios e retornos, Helena antes e após Compra isolada, contratos HTTP de consulta/simulação, FEFO, expiração, Estorno, determinismo, colisões, outro tenant, concorrência e rollback. Para a credencial: chave real utilizável, permissão, exclusividade, symlink/preexistência, ausência de segredo na saída/banco, falha de escrita, falha posterior e falha de commit.

Execute os testes focados durante o desenvolvimento. Antes do merge, execute também a suíte completa e os gates do projeto. Não publique credenciais nem altere o Dashboard nesta entrega.
