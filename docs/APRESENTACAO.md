# Guia vivo da apresentação

Este documento organiza o que deve ser mostrado, explicado e defendido na apresentação final do DataSystemChallenge.

Ele não é o arquivo final de slides. É uma fonte viva para a equipe registrar, durante o desenvolvimento, quais mensagens valem entrar na apresentação, como traduzi-las para uma banca mista e quais perguntas precisam estar preparadas.

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

Não atualizar o documento mecanicamente por toda alteração interna. Atualizar quando a mudança afetar **o que mostramos, o que dizemos ou o que precisamos saber responder**.

## Restrições da apresentação

A apresentação possui:

- **7 minutos** de exposição;
- **3 minutos** para perguntas.

O ensaio principal deve mirar aproximadamente **6min30s a 6min40s**, preservando margem para troca de telas, pequenas pausas e variação natural da fala.

A banca não deve ser tratada como exclusivamente técnica nem exclusivamente de Gestão. A apresentação precisa funcionar para os dois públicos ao mesmo tempo.

## Mensagem central

A mensagem que deve permanecer clara mesmo para quem esquecer detalhes é:

> O DataSystemChallenge é uma plataforma de fidelidade multiempresa configurável e integrável por API. A FATECalçados é o cenário de demonstração, não o sistema inteiro.

A apresentação deve mostrar uma sequência simples:

```text
Empresa define sua política
↓
Lojas herdam ou recebem ajustes permitidos
↓
PDV/ERP envia a venda pela API
↓
plataforma aplica as regras de fidelidade
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
| API REST | O PDV/ERP conversa com a plataforma por uma interface documentada. |
| `X-API-Key` | Cada integração usa uma credencial própria, separada das contas humanas. |
| Constraint de banco | O próprio banco possui uma última barreira contra estados inválidos. |
| Monólito modular | Um único sistema implantável, separado internamente por responsabilidades. |

Usar o termo técnico quando ele demonstrar conhecimento, mas acompanhá-lo de uma consequência compreensível.

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

Ao manter este documento, diferenciar mentalmente três estados:

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

O roteiro deve contar uma história, não percorrer telas aleatoriamente.

### 0:00–0:40 — Problema e proposta

Objetivo: fazer a banca entender rapidamente o que estamos resolvendo.

Mensagem sugerida:

> Programas de fidelidade precisam transformar compras em relacionamento mensurável sem obrigar cada empresa a desenvolver seu próprio motor de regras. Nossa proposta é uma plataforma configurável que recebe vendas dos sistemas já existentes e centraliza a fidelidade.

Em seguida:

> Para demonstrar isso usamos a FATECalçados, mas as regras não são codificadas exclusivamente para ela.

### 0:40–1:20 — Como o produto se organiza

Mostrar visualmente:

```text
Plataforma
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

Usar um exemplo numérico simples.

Direção final esperada:

```text
Empresa define pontos por real
↓
Loja herda a regra
↓
política de arredondamento define a concessão final
↓
Evento pode modificar temporariamente a pontuação
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
4. motor calcula fidelidade
5. Evento/Campanha altera o resultado, quando aplicável
6. Cliente acumula pontos
7. Resgate altera o saldo
8. Dashboard reflete a operação
```

Não abrir módulos sem relação com a história principal.

Se houver risco de lentidão ou navegação excessiva, usar uma combinação de demonstração real + telas previamente preparadas, sem fingir que uma captura é uma execução ao vivo.

### 4:15–5:15 — O que a Gestão consegue enxergar

Quando o dashboard estiver pronto, priorizar os indicadores exigidos pelo cenário e aqueles que ajudam a explicar o programa:

- clientes ativos;
- ticket médio;
- total/custo de descontos;
- ranking por pontos acumulados;
- evolução temporal;
- total de clientes;
- distribuição por níveis;
- pontos acumulados x resgatados;
- taxa de recompra, se estiver disponível de forma coerente.

Não tentar explicar todos os gráficos. Selecionar dois ou três para responder:

> "O programa está sendo usado e qual impacto ele está gerando?"

### 5:15–6:00 — Por que podemos confiar no fluxo

Este trecho é onde a banca técnica recebe evidência sem transformar a apresentação em uma aula de código.

Escolher poucas garantias que tenham consequência clara:

- isolamento entre Empresas;
- credenciais próprias de integração;
- venda idempotente;
- histórico preservado mesmo quando configurações mudam;
- PostgreSQL como defesa final de integridade;
- API documentada por OpenAPI.

Exemplo:

> Se a conexão do PDV cair depois de enviar uma venda, ele pode tentar novamente. A plataforma reconhece a mesma operação e não duplica a Compra nem a fidelidade.

Números de testes podem ser usados como evidência complementar, mas não devem substituir a demonstração do comportamento.

### 6:00–6:30 — Fechamento

Retomar o valor em uma frase:

> A empresa controla sua política de fidelidade, integra seus sistemas existentes e acompanha o resultado sem depender de regras fixas no software.

Conectar novamente à FATECalçados:

> A FATECalçados demonstra essa capacidade com dados e regras próprias, mas a arquitetura foi construída para que outra empresa possa ser configurada sem reescrever o produto.

### 6:30–7:00 — Margem

Não planejar conteúdo essencial para este intervalo.

Usar como margem para:

- troca entre slides e sistema;
- pequenas pausas;
- alguma demora de demonstração;
- fechamento sem pressa.

## Estrutura sugerida de slides

Não é obrigatório usar exatamente esta quantidade, mas a apresentação final deve permanecer curta.

1. **Problema + proposta** — uma frase e uma imagem/diagrama simples.
2. **Uma plataforma, várias empresas e lojas** — estrutura multiempresa.
3. **Regras configuráveis** — exemplo de política de fidelidade.
4. **Da venda ao benefício** — fluxo ponta a ponta e entrada na demonstração.
5. **Resultado para a Gestão** — dashboard e indicadores.
6. **Confiabilidade da solução** — API, isolamento, idempotência e histórico em linguagem simples.
7. **Fechamento** — mensagem central e resultado alcançado.

Se a demonstração real ocupar a tela durante parte do roteiro, não é necessário manter um slide separado aberto para cada etapa.

## Banco de mensagens do projeto

### Mensagens já sustentadas pelo produto integrado

- Empresa é o tenant principal.
- Uma Empresa pode possuir várias Lojas.
- Administrador possui escopo corporativo; Gestor possui escopo explícito por Loja.
- Configuração de fidelidade segue padrão do produto → Empresa → override permitido da Loja.
- A API é versionada e documentada por OpenAPI/Swagger/ReDoc.
- Integrações possuem credenciais próprias com escopo `EMPRESA` ou `LOJAS`.
- Compra é recebida por `POST /api/v1/compras/`.
- A mesma venda externa é identificada por `Loja + identificador_externo`.
- Retry equivalente não cria uma segunda Compra.
- Fatos históricos da Compra são imutáveis pelos caminhos normais do domínio.

### Mensagens previstas para a vertical final

Estas só devem migrar para o bloco de mensagens implementadas depois da respectiva entrega:

- cálculo e armazenamento histórico de pontos;
- política configurável de precisão/arredondamento de pontos;
- campanhas/eventos temporários;
- resgate;
- níveis configuráveis;
- indicadores do dashboard calculados sobre o fluxo completo.

## Como registrar uma nova entrega aqui

Quando uma feature relevante for integrada, responder:

1. O que mudou para o usuário ou para a Gestão?
2. O que mudou no fluxo de demonstração?
3. Existe um exemplo simples que explique a regra?
4. Existe uma garantia técnica que vale traduzir para a banca?
5. Surgiu uma nova limitação que pode virar pergunta?
6. Alguma pergunta do FAQ precisa mudar?

Se todas as respostas forem "não", provavelmente a mudança não precisa alterar a apresentação.

## FAQ — perguntas prováveis da banca

As respostas abaixo são direções curtas. Na banca, responder primeiro em aproximadamente 20–30 segundos e aprofundar somente se houver pedido.

### "Isso substitui o PDV?"

Não. O PDV continua responsável por venda, pagamento, estoque, caixa e fiscal. A plataforma recebe os fatos necessários da venda e executa o domínio de fidelidade.

### "Por que usar API em vez de cadastrar cada venda manualmente?"

Porque a fidelidade precisa acompanhar os sistemas que a empresa já utiliza. A API permite que PDV ou ERP envie a venda de forma padronizada e documentada, sem duplicar operação humana.

### "O que acontece se o PDV enviar a mesma venda duas vezes?"

A Compra é idempotente. A combinação Loja + identificador externo representa a mesma operação; um retry equivalente retorna a Compra existente em vez de criar outra.

### "Como vocês impedem uma empresa de acessar os dados de outra?"

Empresa é o tenant principal. Usuários, Gestores e integrações operam dentro de escopos validados no backend; alterar apenas um ID ou URL não deve ampliar acesso.

### "Por que a FATECalçados não está hardcoded?"

Porque ela é o cenário de demonstração. Regras que podem variar entre empresas são tratadas como configuração; invariantes de segurança e integridade permanecem no código.

### "O que uma empresa consegue configurar?"

A resposta deve refletir apenas o que estiver integrado. Atualmente existe configuração hierárquica de fidelidade com parâmetros da Empresa e override de `pontos_por_real` por Loja. Novos parâmetros devem ser adicionados à resposta somente após implementação.

### "Se a empresa mudar uma regra, as compras antigas mudam?"

Não devem mudar. A arquitetura exige que operações históricas guardem o resultado e os parâmetros efetivamente aplicados. Enquanto uma parte dessa vertical ainda não estiver implementada, explicar como decisão arquitetural e não como funcionalidade pronta.

### "Por que vocês escolheram um monólito modular e não microserviços?"

Porque o prazo e o domínio pedem consistência transacional e velocidade de entrega. O sistema continua separado internamente por módulos, mas evita a complexidade operacional de serviços distribuídos antes de existir necessidade real.

### "Por que Django/PostgreSQL?"

Django oferece uma base madura para domínio, autenticação, validação e API no prazo da entrega. PostgreSQL é o banco de referência e permite constraints e transações que reforçam as invariantes críticas do sistema.

### "Como as integrações são autenticadas?"

Cada integração possui uma credencial própria `X-API-Key`, separada das contas humanas. O segredo bruto é mostrado somente na emissão e o sistema persiste apenas seu hash.

### "Como foi usada inteligência artificial no projeto?"

IA foi usada como apoio em análise, especificação, implementação assistida, testes e revisão. A equipe fechou decisões, executou testes reais, revisou diffs e assumiu responsabilidade pelo que foi integrado. Quando faltou uma decisão, a implementação foi interrompida em vez de inventar a regra.

### "Quais são as limitações atuais?"

Responder com as limitações realmente existentes na versão final. Não esconder limitações e não citar como problema algo que já foi resolvido. Manter esta resposta atualizada conforme o projeto evoluir.

### "Como vocês sabem que funciona?"

Responder combinando demonstração e evidência: testes automatizados dos fluxos críticos, validação em PostgreSQL, revisão de migrations/constraints, validação do OpenAPI e comportamento demonstrado no sistema. Evitar responder apenas com quantidade de testes.

### "O sistema suporta mais de uma Loja?"

Sim. Uma Empresa possui `1..N` Lojas; Administradores têm visão corporativa e Gestores podem ser limitados às Lojas explicitamente atribuídas.

### "O que acontece quando a internet falha durante o envio de uma venda?"

O sistema externo pode repetir a requisição. A idempotência impede que o retry equivalente gere outra Compra. Quando a pontuação estiver integrada, a mesma garantia deve abranger a concessão de fidelidade de forma atômica.

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

Não transformar uma resposta de 20 segundos em uma nova apresentação.

## Checklist antes de fechar os slides

- [ ] o roteiro ensaiado fica abaixo de 7 minutos;
- [ ] existe margem de pelo menos 20 segundos;
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
