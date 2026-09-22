# Workflow de desenvolvimento

Este fluxo aplica as convenções de [contribuição](../CONTRIBUTING.md) e o acompanhamento de [coordenação](COORDENACAO.md).

Entender → fechar decisões → Issue → branch → Codex → implementação incremental → validação com evidência → revisão do diff → PR → Squash and merge.

1. **Entender:** ler o problema, as restrições e a documentação. Separar fatos de suposições.
2. **Fechar decisões:** registrar as regras acordadas e identificar o que segue em aberto. Não inventar uma decisão pendente.
3. **Issue:** definir responsável, objetivo, critérios de aceite e dependências; acompanhar o item no Kanban.
4. **Branch:** partir de `main`, usar `<id>/<tipo>/<descricao>` e confirmar a branch antes de editar.
5. **Codex:** fornecer a Issue e as decisões vigentes; revisar as sugestões e alterações assistidas.
6. **Implementação incremental:** fazer mudanças verificáveis e commits em Conventional Commits, com descrição em português. Não aumentar o escopo silenciosamente; registrar divergências e bloqueios.
7. **Validação com evidência:** executar os testes e comandos pertinentes e registrar os resultados reais. Não afirmar sucesso sem evidência.
8. **Revisão do diff:** conferir arquivos, migrations, escopo e dados sensíveis antes do PR.
9. **PR:** explicar mudanças, validação e pendências; incluir `Closes #<numero>` e mover o item para `Revisão`.
10. **Squash and merge:** integrar após revisão, com título em Conventional Commits, e mover para `Concluído` quando os critérios de aceite estiverem atendidos.

No bootstrap Django, os gates são `uv sync`, `check`, `makemigrations --check`, `migrate`, `test`, `git diff --check` e `uv lock --check` quando o lock mudar. As variáveis locais ficam fora do Git e o PostgreSQL usa banco e volume próprios.
