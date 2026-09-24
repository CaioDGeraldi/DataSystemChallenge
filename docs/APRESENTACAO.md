# Guia vivo da apresentação

Este documento organiza o que deve ser mostrado, explicado e defendido na apresentação final do DataSystemChallenge.

Ele não é o arquivo final de slides. É a fonte viva para registrar quais mensagens valem entrar na apresentação, como traduzi-las para uma banca mista e quais perguntas precisam estar preparadas.

## Identidade da solução

A nomenclatura usada na banca deve ser consistente:

```text
DataSystemChallenge
→ projeto, repositório e contexto do desafio

Retorna
→ marca fictícia do produto de fidelidade

FATECalçados
→ empresa fictícia usada como cenário de demonstração
```

Na apresentação, usar **Retorna** como nome do produto.

A identidade visual aprovada está documentada em `docs/IDENTIDADE_VISUAL.md` e os assets ficam em `assets/retorna/`.

## Regra de atualização

Sempre que uma mudança alterar materialmente algum destes pontos, revisar este arquivo:

- proposta de valor;
- fluxo demonstrável;
- regra de negócio relevante;
- configuração disponível;
- indicador do dashboard;
- segurança ou isolamento multiempresa;
- integração por API;
- limitação conhecida;
- decisão arquitetural que precise ser defendida;
- evidência relevante de funcionamento;
- pergunta provável da banca.

Não atualizar mecanicamente por toda alteração interna. Atualizar quando a mudança afetar **o que mostramos, o que dizemos ou o que precisamos saber responder**.

## Restrições da apresentação

A apresentação possui:

- **7 minutos** de exposição;
- **3 minutos** para perguntas.

O ensaio principal deve mirar aproximadamente **6min30s a 6min40s**, preservando margem para troca de telas, pequenas pausas e variação natural da fala.

A banca não deve ser tratada como exclusivamente técnica nem exclusivamente de Gestão. A apresentação precisa funcionar para os dois públicos ao mesmo tempo.

## Mensagem central

A mensagem que deve permanecer clara mesmo para quem esquecer detalhes é:

> **Retorna é uma plataforma de fidelidade multiempresa, configurável e integrável por API. A FATECalçados é o cenário usado para demonstrar seu funcionamento, não o sistema inteiro.**

A apresentação deve mostrar uma sequência simples:

```text
Empresa define sua política
↓
Lojas herdam ou recebem ajustes permitidos
↓
PDV/ERP envia a venda pela API
↓
Retorna aplica as regras de fidelidade
↓
Cliente acumula e utiliza benefícios
↓
Gestão acompanha o resultado no dashboard
```

Cada etapa só deve ser apresentada como funcional quando estiver efetivamente integrada na `main`.

## Como falar para uma banca mista

Sempre explicar primeiro **por que aquilo importa**, depois **como garantimos**.

Exemplo:

```text
Negócio:
"Se o PDV repetir uma venda por falha de conexão, o cliente não pode ganhar pontos duas vezes."

Tecnologia:
"Por isso a API trata a venda de forma idempotente usando Loja + identificador externo e uma constraint no PostgreSQL."
```

A primeira frase atende Gestão. A segunda demonstra solidez técnica.

Evitar iniciar explicações com framework, classe, migration ou nome de função quando o conceito puder ser explicado pelo efeito produzido.

### Traduções úteis

| Termo técnico | Forma preferida na apresentação |
| --- | --- |
| Multiempresa / tenant | Uma plataforma atende várias empresas mantendo os dados isolados. |
| Idempotência | A mesma venda enviada novamente não gera uma segunda operação. |
| `PROTECT` | Registros históricos não desaparecem porque outro cadastro foi excluído. |
| Snapshot | Guardamos a regra realmente aplicada naquele momento para o histórico não mudar depois. |
| Override de Loja | A Loja herda a regra da Empresa e só guarda a exceção quando ela é permitida. |
| API REST | O PDV/ERP conversa com a Retorna por uma interface documentada. |
| `X-API-Key` | Cada integração usa uma credencial própria, separada das contas humanas. |
| Constraint de banco | O próprio banco possui uma última barreira contra estados inválidos. |
| Monólito modular | Um único sistema implantável, separado internamente por responsabilidades. |

## Como explicar a API

A API é uma parte central da proposta do produto, mas não deve ser apresentada como uma coleção de endpoints.

Mensagem de negócio:

> A Retorna não precisa substituir o sistema que a loja já usa. O PDV, ERP ou e-commerce envia a venda para a API, e a Retorna aplica as regras de fidelidade e devolve o resultado conforme o fluxo implementado.

Mensagem técnica complementar:

> As integrações usam credenciais próprias com escopo de Empresa ou Loja; os contratos são versionados, Compras e Resgates possuem idempotência e a documentação técnica é publicada em OpenAPI.

Responsabilidades atuais da API:

- health da aplicação;
- autenticação de integrações;
- contexto autorizado da credencial;
- isolamento Empresa/Loja;
- registro idempotente de Compra e concessão atômica de pontos;
- retorno de `pontos_base`, `pontos_concedidos` e `expira_em` no bloco `fidelidade` de `POST /api/v1/compras/`;
- registro idempotente de Resgate, consumo de Lotes e retorno do desconto por `POST /api/v1/resgates/`;
- contrato versionado e documentação OpenAPI.

Fluxo de concessão com a F3.03, preservado na F3.04:

```text
PDV/ERP
↓
envia fatos da Compra
↓
Retorna resolve a política e a campanha aplicável à data da venda
↓
calcula fidelidade
↓
persiste Compra + Lote + aplicação da campanha atomicamente
↓
devolve o resultado
```

Compra e Lote são gravados juntos: se a concessão falhar, a nova Compra também é desfeita. Retry equivalente devolve a mesma Compra e o mesmo Lote, sem duplicar ou recalcular.

Compras anteriores ao motor não receberam backfill. Seu retry retorna `fidelidade: null`: não inventamos uma política histórica que não foi registrada.

Na F3.04, o PDV pode solicitar Resgate desses pontos: a Retorna valida mínimo, incremento e saldo elegível, consome Lotes por vencimento e devolve o desconto. Resgate e alocações são gravados juntos; a configuração aplicada permanece no histórico.

Direção da vertical, somente após as fases correspondentes serem integradas:

- consultar informações necessárias de Cliente/saldo;
- expor transparência de configuração quando houver caso de uso real.

Não dizer que esses itens futuros já existem.

## Escrita dos slides

Preferir:

- uma ideia principal por slide;
- título que já comunique a conclusão;
- no máximo três ou quatro informações visuais principais;
- frases curtas;
- diagramas simples;
- números grandes quando houver indicador relevante;
- telas reais do produto quando elas explicarem melhor que texto.

Evitar:

- parágrafos;
- copiar documentação para o slide;
- telas cheias de código;
- diagramas com dezenas de entidades;
- explicar tecnologia sem relacioná-la ao problema;
- prometer funcionalidade que ainda não está funcionando;
- apresentar uma lista extensa de frameworks como se fosse proposta de valor.

A fala deve complementar o slide. O apresentador não deve simplesmente ler o conteúdo projetado.

## Status do conteúdo

```text
IMPLEMENTADO
→ pode ser demonstrado e afirmado como funcional

PLANEJADO
→ pode ser citado apenas como direção, se realmente necessário

A CONFIRMAR
→ não deve virar afirmação ou número do slide
```

Na apresentação final, priorizar quase exclusivamente o que estiver **IMPLEMENTADO**.

## Roteiro-base para 7 minutos

### 0:00–0:40 — Problema e proposta

Objetivo: fazer a banca entender rapidamente o que estamos resolvendo.

Mensagem sugerida:

> Programas de fidelidade precisam transformar compras em relacionamento mensurável sem obrigar cada empresa a desenvolver seu próprio motor de regras. Criamos a Retorna: uma plataforma configurável que recebe vendas dos sistemas já existentes e centraliza a fidelidade.

Em seguida:

> Para demonstrar isso usamos a FATECalçados, mas as regras não são codificadas exclusivamente para ela.

### 0:40–1:20 — Como o produto se organiza

Mostrar visualmente:

```text
Retorna
├── Empresa A
│   ├── Loja 1
│   └── Loja 2
└── Empresa B
    └── Loja 1
```

Explicar em linguagem de negócio:

- cada Empresa possui sua política;
- Lojas herdam a configuração;
- exceções locais existem somente onde o produto permite;
- dados e acessos ficam isolados entre Empresas.

Não gastar tempo apresentando models individualmente.

### 1:20–2:00 — Regra configurável

> Cada empresa pode definir como os pontos são concedidos.

```text
Compra: R$ 49,90
Regra: 1,25 ponto/R$
Resultado bruto: 62,3750
Política da Empresa: 2 casas + HALF_UP
Resultado concedido: 62,38 pontos
```

O armazenamento interno suporta quatro casas. A Empresa escolhe precisão 0/1/2/4 e modo HALF_UP/DOWN/UP. A Loja pode sobrescrever `pontos_por_real`, mas não precisão/arredondamento. O histórico guarda o resultado e a política realmente aplicada.

Exemplo adicional da F3.03:

> Uma campanha altera temporariamente a concessão sem mudar a regra permanente da Empresa ou da Loja.

```text
Regra base: 1 ponto/R$1
Campanha: 2x pontos
Compra: R$ 200
Resultado: 400 pontos
```

O Administrador escolhe período e escopo da campanha. A Retorna aplica o multiplicador antes do arredondamento final e registra a origem no histórico. Para caber no roteiro, escolher um dos exemplos para o slide e deixar o outro para perguntas.

Direção final esperada:

```text
Empresa define pontos por real
↓
Loja herda a regra
↓
Evento aplicável modifica temporariamente a pontuação
↓
política de arredondamento define a concessão final
```

Somente incluir no slide as partes já implementadas no momento da apresentação.

O objetivo é mostrar que a regra pertence ao negócio e não está espalhada em código específico da FATECalçados.

### 2:00–4:15 — Demonstração ponta a ponta

Esta é a parte central da apresentação.

A demonstração final deve procurar seguir uma única venda ao longo do sistema:

```text
1. Empresa/Loja configurada
2. integração envia Compra
3. API aceita a operação
4. motor calcula pontos base
5. aplica Evento/Campanha quando cabível, depois o arredondamento final
6. Cliente acumula pontos
7. API recebe Resgate e consome os Lotes válidos
8. Retorna devolve o desconto e preserva o resultado nos retries
9. Dashboard reflete a operação (etapa futura)
```

Na F3.04, o roteiro inclui criar uma campanha 2x, registrar a venda e mostrar os pontos e a expiração. Em seguida, enviar `POST /api/v1/resgates/` com 200 pontos e mostrar o desconto. Repetir Compra e Resgate evidencia que o histórico não é recalculado nem consumido novamente, inclusive após mudar a política. O Resgate calcula saldo a partir dos Lotes válidos e consumos anteriores; não existe saldo materializado nem endpoint público de consulta. Bônus/descontos percentuais e dashboard continuam futuros.

Exemplo para a FATECalçados:

```text
200 pontos
× R$ 0,05 por ponto
= R$ 10,00 de desconto
```

> A Retorna consome primeiro os pontos que vencem antes. Se o PDV repetir o pedido por falha de conexão, recebe o mesmo desconto, sem consumir pontos novamente.

O instante do Resgate vem do servidor: o PDV não pode informar uma data passada para usar pontos expirados. A quantidade solicitada é inteira, mas pode consumir frações de vários Lotes. O desconto e os parâmetros aplicados permanecem registrados mesmo quando a Empresa muda suas regras.

Na F3.05, a Gestão permite ao Administrador configurar nomes e pontos mínimos dos níveis por Empresa. Para a FATECalçados, Bronze em zero, Prata em 1.000 e Ouro em 5.000 são exemplos que podem ser cadastrados, sem nomes fixos no produto nem seed automático. A classificação está disponível como serviço de domínio; não há tela do Cliente nem API pública de níveis nesta fase.

> O nível reconhece o progresso histórico. Um Cliente que acumulou 5.200 pontos permanece Ouro ao resgatar 5.000. O saldo cai, mas o progresso não é apagado. Ele pode ser Ouro e estar ativo ou inativo.

Expiração e inatividade não reduzem o nível. Alterar as faixas da Empresa pode mudar a classificação atual. Não associar Prata/Ouro a percentuais ou benefícios: descontos por nível, bônus e outras vantagens continuam fora desta entrega. A validação local da F3.05 deve preceder sua demonstração.

Não abrir módulos sem relação com a história principal.

Se houver risco de lentidão ou navegação excessiva, usar uma combinação de demonstração real + telas previamente preparadas, sem fingir que uma captura é uma execução ao vivo.

### 4:15–5:15 — O que a Gestão consegue enxergar

Quando o dashboard estiver pronto, priorizar os indicadores exigidos pelo cenário e aqueles que ajudam a explicar o programa.

### Indicadores obrigatórios do cenário

- clientes ativos;
- ticket médio;
- total/custo de descontos;
- ranking por pontos acumulados;
- evolução temporal.

### Indicadores complementares do produto

- total de clientes;
- distribuição por níveis;
- pontos acumulados x resgatados;
- custo consolidado do programa em R$, quando houver base real para o cálculo;
- taxa de recompra, se estiver disponível de forma coerente.

Não tentar explicar todos os gráficos. Selecionar dois ou três para responder:

> "O programa está sendo usado e qual impacto ele está gerando?"

A taxa de recompra é especialmente coerente com a marca Retorna porque mede se o cliente voltou a comprar, mas só deve ser exibida quando sua definição estiver fechada e o cálculo implementado.

### 5:15–6:00 — Por que podemos confiar no fluxo

Escolher poucas garantias que tenham consequência clara:

- isolamento entre Empresas;
- credenciais próprias de integração;
- Compra e Resgate idempotentes;
- histórico de Compra, Lote, Resgate e desconto preservado mesmo quando configurações mudam;
- pedidos simultâneos não podem gastar os mesmos pontos;
- PostgreSQL como defesa final de integridade;
- API documentada por OpenAPI.

Exemplo:

> Se a conexão do PDV cair depois de enviar uma venda, ele pode tentar novamente. A Retorna devolve a mesma Compra e o mesmo Lote, sem duplicar nem recalcular pontos. Compra e concessão são gravadas juntas: se uma falhar, a nova operação inteira é desfeita.

Para o Resgate, a mesma garantia protege o desconto: registro e consumo são gravados juntos. Com saldo de 100 pontos e dois pedidos simultâneos de 100, somente um pode consumir esse saldo; o outro recebe saldo insuficiente.

### 6:00–6:30 — Fechamento

> A Retorna permite que cada empresa controle sua política de fidelidade, integre os sistemas que já utiliza e acompanhe os resultados sem depender de regras fixas no software.

Conectar novamente à FATECalçados:

> A FATECalçados demonstra essa capacidade com dados e regras próprias, mas a arquitetura foi construída para que outra empresa possa ser configurada sem reescrever o produto.

### 6:30–7:00 — Margem

Não planejar conteúdo essencial para este intervalo.

## Estrutura sugerida de slides

1. **Retorna — problema + proposta**
2. **Uma plataforma, várias empresas e lojas**
3. **Regras configuráveis**
4. **Da venda ao benefício**
5. **Resultado para a Gestão**
6. **Confiabilidade da solução**
7. **Fechamento**

A demonstração real pode substituir parte dos slides intermediários.

## Banco de mensagens do projeto

### Mensagens já sustentadas pelo produto integrado

As mensagens abaixo contemplam a F3.02 validada e sua integração junto com este documento.

- Retorna é a marca fictícia do produto desenvolvido no DataSystemChallenge.
- FATECalçados é cenário demonstrativo, não regra fixa do domínio.
- Empresa é o tenant principal.
- Uma Empresa pode possuir várias Lojas.
- Administrador possui escopo corporativo; Gestor possui escopo explícito por Loja.
- Configuração de fidelidade segue padrão do produto → Empresa → override permitido da Loja.
- A API é versionada e documentada por OpenAPI/Swagger/ReDoc.
- Integrações possuem credenciais próprias com escopo `EMPRESA` ou `LOJAS`.
- Compra é recebida por `POST /api/v1/compras/`.
- A mesma venda externa é identificada por `Loja + identificador_externo`.
- Retry equivalente retorna a mesma Compra e o mesmo Lote, sem duplicação ou recálculo.
- Fatos históricos da Compra são imutáveis pelos caminhos normais do domínio.
- Novas Compras geram LotePontos atomicamente, inclusive quando a taxa concede zero pontos.
- A Empresa configura precisão e arredondamento; o Lote preserva a política e o resultado aplicados.
- Alterações posteriores de parâmetros não mudam os pontos históricos.
- Compras legadas sem Lote retornam `fidelidade: null`, sem backfill implícito.

### Mensagens da F3.03 para integração após validação

- Campanhas temporárias com multiplicador não alteram a configuração permanente.
- A data da venda define a aplicabilidade, mesmo quando o PDV envia depois.
- Administrador cria campanhas para a Empresa ou Lojas selecionadas e cancela sem apagar histórico.
- Campanhas do mesmo efeito, período e Loja não são combinadas; o conflito é rejeitado.
- Compra, Lote e aplicação histórica são gravados juntos; retries preservam o resultado original.
- Cancelar uma campanha impede novas concessões por ela, mas não altera pontos já concedidos.

### Mensagens da F3.04

- Resgate é recebido por `POST /api/v1/resgates/`, com a credencial `X-API-Key` da integração.
- O Cliente precisa ter pontos válidos suficientes e respeitar mínimo e incremento corporativos.
- O consumo prioriza a expiração mais próxima e preserva os Lotes originais.
- `200 pontos × R$ 0,05 = R$ 10,00` é registrado como desconto histórico.
- Retry equivalente retorna o mesmo Resgate, sem novo consumo ou recálculo financeiro.
- O saldo é derivado, e o fluxo transacional serializa disputas pelo mesmo Cliente.
- Não há backdating, cancelamento, estorno ou consulta pública de saldo nesta fase.

### Mensagens da F3.05

- Administrador configura níveis da própria Empresa, com nomes livres e thresholds em ordem crescente.
- Uma configuração com níveis começa em zero; Empresa sem configuração não atribui nível implícito.
- Nível usa pontos historicamente concedidos, incluindo Lotes expirados, sem descontar Resgates.
- Saldo, nível e atividade representam dimensões distintas do Cliente.
- Alterações nas faixas mudam a classificação atual sem reescrever o histórico de pontos.
- A classificação é um serviço de domínio; não há API pública, área do Cliente ou benefícios por nível nesta fase.

### Mensagens previstas para a vertical final

Estas só devem migrar para o bloco de mensagens implementadas depois da respectiva entrega:

- indicadores do dashboard calculados sobre o fluxo completo.

## Como registrar uma nova entrega aqui

Quando uma feature relevante for integrada, responder:

1. O que mudou para o usuário ou para a Gestão?
2. O que mudou no fluxo de demonstração?
3. Existe um exemplo simples que explique a regra?
4. Existe uma garantia técnica que vale traduzir para a banca?
5. Surgiu uma nova limitação que pode virar pergunta?
6. Alguma pergunta do FAQ precisa mudar?

## FAQ — perguntas prováveis da banca

As respostas abaixo são direções curtas. Na banca, responder primeiro em aproximadamente 20–30 segundos e aprofundar somente se houver pedido.

### "O que é a Retorna?"

É a marca do produto desenvolvido no desafio: uma plataforma de fidelidade multiempresa, configurável e integrável por API. O DataSystemChallenge continua sendo o projeto/repositório e a FATECalçados é o cenário demonstrativo.

### "Isso substitui o PDV?"

Não. O PDV continua responsável por venda, pagamento, estoque, caixa e fiscal. A Retorna recebe os fatos necessários da venda e executa o domínio de fidelidade.

### "Então qual é a função da API?"

Conectar a Retorna aos sistemas que a empresa já utiliza. Ela autentica integrações, controla escopo Empresa/Loja, recebe os fatos da Compra e devolve a fidelidade calculada. Também recebe pedidos de Resgate e devolve o desconto calculado a partir dos pontos consumidos. Cada operação preserva seu histórico nos retries. A consulta pública de saldo continua futura; as regras de fidelidade ficam na Retorna, sem duplicação no PDV.

### "Por que usar API em vez de cadastrar cada venda manualmente?"

Porque a fidelidade precisa acompanhar os sistemas que a empresa já utiliza. A API permite que PDV, ERP ou e-commerce envie a venda de forma padronizada e documentada, sem duplicar operação humana.

### "O que acontece se o PDV enviar a mesma venda duas vezes?"

A combinação Loja + identificador externo identifica a operação. Se os fatos forem equivalentes, a Retorna retorna a mesma Compra e o mesmo Lote, sem duplicar nem recalcular pontos, mesmo se a política tiver mudado depois. Se os fatos divergirem, informa conflito.

### "Como vocês impedem uma empresa de acessar os dados de outra?"

Empresa é o tenant principal. Usuários, Gestores e integrações operam dentro de escopos validados no backend; alterar apenas um ID ou URL não deve ampliar acesso.

### "Por que a FATECalçados não está hardcoded?"

Porque ela é o cenário de demonstração. Regras que podem variar entre empresas são tratadas como configuração; invariantes de segurança e integridade permanecem no código.

### "O que uma empresa consegue configurar?"

A Empresa define os parâmetros de fidelidade, incluindo taxa, validade, precisão de 0/1/2/4 casas e modo HALF_UP/DOWN/UP. A Loja pode sobrescrever `pontos_por_real`, mas herda a precisão e o arredondamento corporativos. Cada concessão guarda a política aplicada para preservar o histórico.

### "Se a empresa mudar uma regra, as compras antigas mudam?"

Não. Os pontos antigos permanecem como foram concedidos. O Lote registra resultado bruto, resultado concedido e política aplicada; mudar a configuração afeta novas operações, sem reescrever esse histórico. Repetir uma venda já registrada também não recalcula seus pontos.

### "Uma campanha muda a regra permanente da Loja?"

Não. A Empresa e a Loja continuam com sua regra base. A campanha aplica um multiplicador temporário antes do arredondamento: com 1 ponto por real, campanha 2x e Compra de R$ 200, são concedidos 400 pontos. A Retorna guarda o resultado e a campanha aplicada no histórico.

### "E se o PDV enviar a venda depois que a campanha terminar?"

A Retorna considera a data em que a venda ocorreu. Se ela estava dentro do período, inclusive nos limites, e a campanha não foi cancelada, o multiplicador pode ser aplicado. Os parâmetros permanentes ainda são os vigentes no processamento, pois não existe versionamento temporal completo deles.

### "O que acontece ao cancelar uma campanha?"

Ela deixa de participar de novas concessões, mas os pontos e a origem das concessões anteriores permanecem intactos. Não editamos nem apagamos sua definição: para corrigir uma campanha, o Administrador cancela a antiga e cria outra. Repetir uma venda já registrada devolve o histórico original.

### "Como funciona o arredondamento?"

Cada Empresa escolhe quantas casas usa na concessão e o modo de arredondar: HALF_UP leva a metade para cima, DOWN reduz a fração excedente e UP aumenta quando existe fração excedente. Por exemplo, 62,3750 bruto vira 62,38 com duas casas e HALF_UP. Ambos os valores ficam no histórico.

### "Por que Compras antigas não ganharam pontos automaticamente?"

Porque não havia registro da política aplicada a essas Compras. Não inventamos um histórico que não foi registrado. Por isso não houve backfill: a Compra legada continua sem Lote e seu retry devolve `fidelidade: null`, sem aplicar retroativamente a configuração atual.

### "O que a API devolve depois de registrar uma Compra?"

Além dos dados da Compra, devolve o bloco `fidelidade` com `pontos_base`, `pontos_concedidos` e `expira_em`. Os pontos aparecem como strings com quatro casas decimais. Uma nova operação retorna 201; um retry equivalente retorna 200 com o mesmo histórico. Isso ainda não representa saldo disponível para Resgate.

### "Resgatar ou deixar os pontos expirarem reduz meu nível?"

Não. O nível usa todos os pontos já concedidos; saldo disponível e atividade são conceitos separados. Com 5.200 pontos históricos e Ouro a partir de 5.000, o Cliente continua Ouro após um Resgate ou a expiração de Lotes. A Empresa pode alterar os thresholds e, com isso, mudar a classificação atual. Níveis não concedem benefícios automáticos nesta fase.

### "Como os pontos viram desconto?"

A integração solicita uma quantidade inteira de pontos, respeitando mínimo e incremento. A Retorna consome os Lotes válidos que expiram primeiro e aplica o valor por ponto: 200 pontos a R$ 0,05 dão R$ 10,00. Lotes podem conter frações; o consumo pode combinar essas frações sem perder precisão. O desconto e os parâmetros ficam registrados como fatos históricos.

### "O mesmo saldo pode ser usado em dois caixas ao mesmo tempo?"

O fluxo serializa Resgates do mesmo Cliente e calcula o saldo depois dos consumos anteriores. Se dois pedidos de 100 disputarem saldo de 100, apenas um pode concluir. Se forem retries da mesma operação, devolvemos o histórico original sem consumir novamente.

### "Posso resgatar pontos depois do vencimento usando a data da venda?"

Não. Resgate usa o instante do servidor e só consome Lotes com expiração posterior a esse instante. No instante exato do vencimento o Lote já está expirado. Um retry de Resgate que já foi concluído continua retornando seu resultado histórico mesmo após o vencimento.

### "Por que vocês escolheram um monólito modular e não microserviços?"

Porque o prazo e o domínio pedem consistência transacional e velocidade de entrega. O sistema continua separado internamente por módulos, mas evita a complexidade operacional de serviços distribuídos antes de existir necessidade real.

### "Por que Django/PostgreSQL?"

Django oferece uma base madura para domínio, autenticação, validação e API no prazo da entrega. PostgreSQL é o banco de referência e permite constraints e transações que reforçam as invariantes críticas do sistema.

### "Como as integrações são autenticadas?"

Cada integração possui uma credencial própria `X-API-Key`, separada das contas humanas. O segredo bruto é mostrado somente na emissão e o sistema persiste apenas seu hash.

### "Como foi usada inteligência artificial no projeto?"

IA foi usada como apoio em análise, especificação, implementação assistida, testes e revisão. A equipe fechou decisões, executou testes reais, revisou diffs e assumiu responsabilidade pelo que foi integrado. Quando faltou uma decisão, a implementação foi interrompida em vez de inventar a regra.

### "Quais são as limitações atuais?"

Responder com as limitações realmente existentes na versão final. Não esconder limitações e não citar como problema algo que já foi resolvido.

### "Como vocês sabem que funciona?"

Responder combinando demonstração e evidência: testes automatizados dos fluxos críticos, validação em PostgreSQL, revisão de migrations/constraints, validação do OpenAPI e comportamento demonstrado no sistema.

### "O sistema suporta mais de uma Loja?"

Sim. Uma Empresa possui `1..N` Lojas; Administradores têm visão corporativa e Gestores podem ser limitados às Lojas explicitamente atribuídas.

### "O que acontece quando a internet falha durante o envio de uma venda?"

O sistema externo pode repetir a requisição. A Retorna retorna a mesma Compra e o mesmo Lote, sem duplicar ou recalcular a concessão. Os dois registros são atômicos: se a criação do Lote falhar, a nova Compra também é desfeita. Assim, uma falha não deixa a nova venda registrada pela metade.

## Preparação dos 3 minutos de perguntas

Dividir mentalmente as perguntas em quatro grupos:

```text
Negócio
→ regra, indicador, valor, aplicação real

Produto
→ configuração, fluxo, limitações, experiência

Tecnologia
→ API, segurança, banco, idempotência, arquitetura

Processo
→ equipe, testes, uso de IA, decisões e escopo
```

Para responder:

1. começar pela resposta direta;
2. explicar a consequência para o negócio;
3. acrescentar o mecanismo técnico somente se necessário;
4. quando houver limitação, declarar a limitação e o que foi deliberadamente deixado fora do escopo.

## Checklist antes de fechar os slides

- [ ] o roteiro ensaiado fica abaixo de 7 minutos;
- [ ] existe margem de pelo menos 20 segundos;
- [ ] Retorna é apresentada como produto e DataSystemChallenge como contexto do desafio;
- [ ] a mensagem central aparece no início e no fechamento;
- [ ] a FATECalçados está apresentada como cenário, não como regra hardcoded;
- [ ] nenhuma funcionalidade planejada está sendo apresentada como pronta;
- [ ] a demonstração segue uma única história ponta a ponta;
- [ ] termos técnicos são traduzidos para consequência de negócio;
- [ ] indicadores usados possuem dados reais/coerentes;
- [ ] limitações importantes estão conhecidas pela equipe;
- [ ] cada integrante sabe responder às perguntas de sua frente;
- [ ] o FAQ foi revisado após a última feature relevante;
- [ ] existe plano de contingência para falha na demonstração ao vivo;
