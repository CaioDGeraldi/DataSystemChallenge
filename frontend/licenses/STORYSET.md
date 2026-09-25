# Onboarding — Bro

Ilustração de Storyset / Freepik: https://storyset.com/illustration/onboarding/bro

Fonte local: `FractawModules/frontend/src/illustrations/storyset/welcome_onboarding.svg`,
já sanitizada pelo projeto de referência. Não existe dependência runtime desse repositório.

Arquivos usados exclusivamente no onboarding inicial:

- `public/illustrations/welcome_onboarding-light.svg`
- `public/illustrations/welcome_onboarding-dark.svg`

Ambos preservam geometria, opacidades e referências internas. O accent original
`#4FA7A3` foi trocado por `#5EC33D`. A variante escura troca o tom estrutural
`#263238` por `#8293AD` para distinguir os traços da superfície navy. Os brancos
internos pertencem à ilustração; não há fundo retangular branco nem filtro global.

Os SVGs são decorativos, locais e sem scripts, handlers ou referências externas.
O Vite copia `public/illustrations/` para `dist/illustrations/`; Django resolve as
URLs pelo staticfiles. O template seleciona a variante por CSS conforme o tema.

O asset não é coberto pela licença MIT do Gentelella. Uso com atribuição
Storyset / Freepik no footer da superfície ilustrada. Termos da fonte:
https://storyset.com/terms

Não retirar o crédito ao distribuir a interface. Forms foi removido por não haver
mais uso: formulários operacionais e as duas landings não usam Storysets.
