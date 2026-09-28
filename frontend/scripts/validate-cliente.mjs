import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { compileString } from 'sass';
const css = readFileSync(new URL('../src/styles/retorna/_cliente.scss', import.meta.url), 'utf8');
for (const contrato of ['env(safe-area-inset-bottom, 0px)', 'position: fixed', 'position: static', 'min-width: 48rem', 'min-height: 56px', 'corner-shape: squircle', 'border-radius: 1.25rem', 'forced-colors', "a[aria-current='page']"]) {
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
