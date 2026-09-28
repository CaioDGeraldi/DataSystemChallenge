import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { compileString } from 'sass';
const css = readFileSync(new URL('../src/styles/retorna/_cliente.scss', import.meta.url), 'utf8');
for (const contrato of ['env(safe-area-inset-bottom, 0px)', 'position: fixed', 'position: static', 'min-width: 48rem', 'min-height: 56px', 'corner-shape: squircle', 'border-radius: var(--radius-lg)', 'forced-colors', "a[aria-current='page']"]) {
  assert.ok(css.includes(contrato), contrato);
}
assert.ok(css.includes('calc(7rem + env(safe-area-inset-bottom, 0px))'));
assert.ok(readFileSync(new URL('../src/styles/retorna.scss', import.meta.url), 'utf8').includes('@use "retorna/cliente"'));
console.log('Cliente: navegação responsiva, safe area, alvos de toque, fallback de cantos e forced colors OK.');

// Compile nesting first: these checks cover structural contracts, not visual layout.
const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');
const shell = read('../src/styles/retorna/_shell.scss');
const compiled = compileString(shell + '\n' + css).css;
const rules = [...compiled.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(([, selectors, body]) => ({
  selectors: selectors.trim().split(',').map(selector => selector.trim()),
  declarations: Object.fromEntries(body.trim().split(';').filter(Boolean).map(declaration => {
    const colon = declaration.indexOf(':');
    return [declaration.slice(0, colon).trim(), declaration.slice(colon + 1).trim()];
  })),
}));
const declarations = selector => Object.assign({}, ...rules.filter(rule => rule.selectors.includes(selector)).map(rule => rule.declarations));
for (const selector of ['.management-shell', '.retorna-public-page', '.cliente-page']) {
  const style = declarations(selector);
  assert.equal(style['min-height'], '100dvh', selector);
  assert.equal(style.display, 'flex', selector);
  assert.equal(style['flex-direction'], 'column', selector);
}
assert.match(compiled, /min-height: 100vh;\s*min-height: 100dvh;/);
for (const selector of ['.main', '.retorna-public-main', '.cliente-main']) {
  const style = declarations(selector);
  assert.equal(style.display, 'flex', selector);
  assert.equal(style['flex-direction'], 'column', selector);
  assert.equal(style.flex, '1 0 auto', selector);
  assert.equal(style['min-height'], '0', selector);
}
assert.equal(declarations('.page-wrapper').flex, '1 0 auto');
assert.equal(declarations('.page-wrapper').width, '100%');
assert.equal(declarations('.cliente-page .cliente-main > .page-wrapper')['max-width'], '70rem');
assert.equal(declarations('.cliente-page .cliente-main > .page-wrapper')['margin-inline'], 'auto');
for (const rule of rules) {
  if (rule.selectors.some(selector => selector.endsWith('.cliente-main') || selector.endsWith('.retorna-footer'))) {
    assert.ok(!rule.declarations['max-width'], 'Main e footer não podem limitar a largura do shell');
  }
  if (rule.selectors.some(selector => selector.endsWith('.retorna-footer'))) {
    assert.ok(!['fixed', 'absolute'].includes(rule.declarations.position), 'Footer deve continuar em fluxo');
  }
}
assert.equal(declarations('.retorna-footer').width, '100%');
assert.equal(declarations('.retorna-footer')['flex-shrink'], '0');
const reserves = rules.filter(rule => rule.selectors.includes('.cliente-page .cliente-main'));
assert.equal(reserves[0].declarations['padding-bottom'], 'calc(7rem + env(safe-area-inset-bottom, 0px))');
assert.match(compiled, /@media \(min-width: 48rem\)\s*\{\s*\.cliente-page \.cliente-main\s*\{\s*padding-bottom: 0;/);
const base = read('../../templates/datasystem/base.html');
assert.ok(base.includes('</div></div>\n    {% include \'datasystem/includes/footer.html\' %}\n  </main>'), 'Footer deve ser irmão do conteúdo dentro do main');
assert.ok(read('../../templates/datasystem/gestao_base.html').includes('{% block main_class %}main{% endblock %}'));
assert.ok(read('../../templates/datasystem/cliente/base.html').includes('{% block main_class %}cliente-main{% endblock %}'));
console.log('Shell público/Gestão/Cliente: altura flex, conteúdo limitado, footer em fluxo/full width e reserva mobile OK (estático).');

const cliente = read('../../templates/datasystem/cliente/base.html');
for (const id of ['cliente-programas-panel', 'cliente-conta-panel']) {
  assert.ok(cliente.includes(`aria-controls="${id}" data-user-menu-trigger`));
  assert.ok(cliente.includes(`id="${id}" data-user-menu>`), 'Painel nativo não pode depender de hidden/JS');
}
assert.equal((cliente.match(/<details[^>]+retorna-user-menu/g) ?? []).length, 2);
assert.equal((cliente.match(/name="cliente-topbar"/g) ?? []).length, 2);
for (const text of ['<summary class="retorna-user-trigger"', 'class="tb-avatar" aria-hidden="true"',
  'for programa in programas', 'aria-current="true"', 'Programa atual',
  'name="cliente_id" value="{{ programa.pk }}"', 'data-appearance-open',
  'method="post" action="{% url \'clientes:trocar_programa\' %}"',
  'method="post" action="{% url \'usuarios:logout\' %}"']) assert.ok(cliente.includes(text), text);
assert.equal((cliente.match(/{% csrf_token %}/g) ?? []).length, 2);
assert.ok(!cliente.includes('role="menu"'));
const header = declarations('.cliente-page .cliente-header');
assert.equal(header.display, 'grid');
assert.equal(header['grid-template-columns'], 'auto minmax(0, 1fr) auto');
assert.ok(Number(header['z-index']) > Number(declarations('.cliente-page .cliente-nav')['z-index']));
assert.equal(declarations('.cliente-page .cliente-programa-nome')['text-overflow'], 'ellipsis');
const panels = rules.filter(rule => rule.selectors.includes('.cliente-page .cliente-header .retorna-user-dropdown'));
assert.equal(panels[0].declarations.position, 'absolute');
assert.equal(panels[0].declarations.left, '1rem');
assert.equal(panels[0].declarations.right, '1rem');
assert.equal(panels[0].declarations['overflow-y'], 'auto');
assert.equal(declarations('.cliente-page .cliente-header summary')['min-height'], '44px');
assert.ok(shell.includes('html:not([data-retorna-user-menu-enhanced]) button.retorna-user-trigger'));
const management = read('../../templates/datasystem/includes/topbar.html');
for (const text of ['class="retorna-user-menu"', 'data-user-menu-trigger', 'data-user-menu hidden',
  'aria-controls="retorna-user-dropdown"', 'id="retorna-user-dropdown"']) assert.ok(management.includes(text));

const area = read('../../templates/datasystem/cliente/area.html');
const pontos = read('../../templates/datasystem/cliente/pontos.html');
const resgates = read('../../templates/datasystem/cliente/resgates.html');

for (const contrato of [
  'cliente-grid--inicio',
  'cliente-card--principal',
  'cliente-card--nivel',
  'cliente-card--compacto',
  'cliente-card--ranking',
  'cliente-card-rotulo',
]) assert.ok(area.includes(contrato), contrato);

for (const contrato of [
  'cliente-movimentos',
  'cliente-movimento',
  'cliente-movimento-cabecalho',
  'cliente-movimento-valor',
  'cliente-meta',
]) assert.ok(pontos.includes(contrato), contrato);

for (const contrato of [
  'cliente-movimentos',
  'cliente-movimento',
  'cliente-movimento-cabecalho',
  'cliente-movimento-resumo',
  'cliente-status--realizado',
  'cliente-status--cancelado',
]) assert.ok(resgates.includes(contrato), contrato);

assert.equal(declarations('.cliente-page .cliente-card--principal')['grid-column'], undefined);
for (const selector of ['.cliente-page .cliente-card-cabecalho > div', '.cliente-page .cliente-resumo-linha > div', '.cliente-page .cliente-movimento-cabecalho > div']) {
  assert.equal(declarations(selector)['min-width'], '0', selector);
}
assert.equal(declarations('.cliente-page .cliente-movimento-cabecalho').display, 'flex');
assert.equal(declarations('.cliente-page .cliente-movimento-valor')['font-variant-numeric'], 'tabular-nums');
assert.equal(declarations('.cliente-page .cliente-status--realizado').background, 'var(--success-surface)');
assert.equal(declarations('.cliente-page .cliente-status--cancelado').background, 'var(--danger-surface)');

console.log('Área do Cliente: hierarquia da Home, movimentos de pontos e estados de resgate OK.');
console.log('Topbar Cliente: disclosures nativos, POST/CSRF, conta, associação ARIA, overlay e largura mobile OK (estático).');
