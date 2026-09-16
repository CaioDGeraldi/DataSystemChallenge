# Guia de contribuição

## Identificador de colaborador

Cada pessoa que trabalhar diretamente no GitHub recebe um identificador numérico permanente de três dígitos.

| ID | Colaborador |
| --- | --- |
| `001` | CaioDGeraldi |

Novos colaboradores recebem `002`, `003`, `004` e assim por diante.

IDs não devem ser reutilizados durante o projeto.

## Branches

Formato:

```text
<id>/<tipo>/<descricao>
```

Exemplos:

```text
001/docs/coordenacao-equipe
001/chore/configurar-repositorio
002/feat/importar-dados
003/fix/validar-formulario
```

Tipos recomendados:

- `feat`
- `fix`
- `docs`
- `refactor`
- `test`
- `chore`
- `build`
- `ci`
- `perf`
- `revert`

A descrição deve usar letras minúsculas e hífens.

## Conventional Commits

Formato:

```text
tipo(escopo): descrição
```

Exemplos:

```text
docs(equipe): atualizar guia de coordenação
chore(repo): configurar templates do GitHub
feat(importacao): adicionar leitura de arquivo
fix(validacao): corrigir campo obrigatório
```

A descrição deve ser curta, objetiva e em português.

## Fluxo

```text
Issue
→ Branch
→ Commits
→ Pull Request
→ Revisão
→ Squash and merge
→ main
```

Regras:

1. trabalho relevante começa em uma Issue;
2. cada Issue possui um responsável principal;
3. a branch parte da `main`;
4. o Pull Request deve referenciar a Issue;
5. o título do Pull Request segue Conventional Commits;
6. a integração é feita por **Squash and merge**;
7. o título do squash também segue Conventional Commits.

## Pull Requests

Um Pull Request deve:

- possuir um objetivo;
- explicar o que mudou;
- informar como foi validado;
- evitar alterações sem relação com a Issue.

Use no corpo:

```text
Closes #<numero>
```

para encerrar automaticamente a Issue após a integração.

## GitHub Projects

O quadro Kanban utiliza:

```text
Backlog
Em andamento
Revisão
Concluído
```

As regras de movimentação estão em [Coordenação da equipe](docs/COORDENACAO.md).
