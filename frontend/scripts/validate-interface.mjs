import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { normalizeAppearance, effectiveTheme, readAppearance, writeAppearance, initialFormMode, bindAppearance } from '../src/js/retorna/appearance.js';
const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');
const defaults = { theme: 'system', fontScale: 100, formMode: 'steps' };
for (const invalid of [null, false, [], 'dark', { theme: 'bad', fontScale: 300, formMode: 'bad' }]) assert.deepEqual(normalizeAppearance(invalid), defaults);
assert.deepEqual(normalizeAppearance({ ...defaults, token: 'never store', empresa: 5 }), defaults);
const blocked = { getItem() { throw Error('SecurityError'); }, setItem() { throw Error('QuotaError'); } };
assert.deepEqual(readAppearance(blocked), defaults);
assert.equal(writeAppearance(blocked, defaults), false);
assert.deepEqual(readAppearance({ getItem: () => '{bad' }), defaults);
let saved;
assert.equal(writeAppearance({ setItem: (_, value) => { saved = JSON.parse(value); } }, { ...defaults, cpf: 'excluded' }), true);
assert.deepEqual(saved, defaults);
for (const dark of [true, false]) {
  assert.equal(effectiveTheme('system', dark), dark ? 'dark' : 'light');
  assert.equal(effectiveTheme('light', dark), 'light');
  assert.equal(effectiveTheme('dark', dark), 'dark');
}
assert.equal(initialFormMode(undefined, 'all'), 'all');
assert.equal(initialFormMode('steps', 'all'), 'steps');
assert.equal(initialFormMode('all', 'steps'), 'all');
assert.equal(initialFormMode('invalid', 'invalid'), 'steps');
const bootstrap = read('../../templates/datasystem/includes/appearance_bootstrap.html').replace(/<\/?script>/g, '');
for (const value of [null, 'broken', 'null', '5', JSON.stringify({ theme: 'dark', fontScale: 120, formMode: 'all' })]) {
  const document = { documentElement: { dataset: {} } };
  vm.runInNewContext(bootstrap, { document, localStorage: { getItem: () => value }, window: { matchMedia: () => ({ matches: true }) } });
  const expected = readAppearance({ getItem: () => value });
  assert.equal(document.documentElement.dataset.retornaTheme, effectiveTheme(expected.theme, true));
  assert.equal(Number(document.documentElement.dataset.retornaFontScale), expected.fontScale);
  assert.equal(document.documentElement.dataset.retornaFormMode, expected.formMode);
}
const tokens = read('../src/styles/retorna/_tokens.scss');
const split = tokens.indexOf(":root[data-retorna-theme='dark']");
const parse = source => Object.fromEntries([...source.matchAll(/--([\w-]+):\s*(#[\da-f]{6});/gi)].map(m => [m[1], m[2]]));
const light = parse(tokens.slice(0, split)), dark = { ...light, ...parse(tokens.slice(split)) };
function luminance(hex) {
  const channels = hex.slice(1).match(/../g).map(x => parseInt(x, 16) / 255).map(x => x <= .04045 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4);
  return channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722;
}
function contrast(a, b) { const [hi, lo] = [luminance(a), luminance(b)].sort((a,b) => b-a); return (hi+.05)/(lo+.05); }
for (const palette of [light, dark]) {
  for (const surface of ['surface', 'background', 'surface-secondary']) {
    for (const text of ['text', 'text-muted', 'primary']) assert.ok(contrast(palette[text], palette[surface]) >= 4.5, `${text}/${surface}`);
    for (const control of ['control-border', 'focus']) assert.ok(contrast(palette[control], palette[surface]) >= 3, `${control}/${surface}`);
  }
  for (const status of ['danger', 'success', 'warning', 'info']) assert.ok(contrast(palette[status], palette[`${status}-surface`]) >= 4.5, status);
  assert.ok(contrast(palette['primary-text'], palette.primary) >= 4.5);
  for (const text of ['sidebar-text', 'sidebar-muted', 'accent']) assert.ok(contrast(palette[text], palette.sidebar) >= 4.5);
}
const base = read('../../templates/datasystem/base.html');
assert.ok(base.indexOf('appearance_bootstrap.html') < base.indexOf('rel="stylesheet"'));
assert.ok(base.includes('href="#conteudo"') && base.includes('<main id="conteudo"'));
assert.ok(read('../src/styles/retorna/_base.scss').includes('prefers-reduced-motion'));
assert.ok(read('../src/styles/retorna/_base.scss').includes('forced-colors'));
console.log('Preferências, bootstrap, fallback de armazenamento, precedência de formulários e contraste dos tokens: OK.');

// System changes update the page; explicit themes ignore OS changes.
for (const theme of ['system', 'light', 'dark']) {
  let onChange;
  const media = { matches: false, addEventListener: (_, callback) => { onChange = callback; } };
  globalThis.document = { documentElement: { dataset: {} }, querySelector: () => null };
  globalThis.window = { localStorage: { getItem: () => JSON.stringify({ theme }) }, matchMedia: () => media };
  bindAppearance();
  assert.equal(document.documentElement.dataset.retornaTheme, effectiveTheme(theme, false));
  media.matches = true;
  onChange();
  assert.equal(document.documentElement.dataset.retornaTheme, effectiveTheme(theme, true));
}
delete globalThis.document;
delete globalThis.window;
console.log('Mudanças de tema do sistema em runtime e escolhas explícitas: OK.');

const illustration = read('../../templates/datasystem/includes/illustration.html');
for (const theme of ['light', 'dark']) {
  const name = `welcome_onboarding-${theme}.svg`;
  const svg = read(`../public/illustrations/${name}`);
  assert.ok(svg.includes('<svg') && svg.includes('viewBox="0 0 500 500"'));
  assert.ok(!/<script|<foreignObject|\son\w+\s*=/i.test(svg));
  assert.ok(!/(?:href|xlink:href)\s*=\s*["'](?!#)/i.test(svg));
  assert.ok(!/url\(\s*["']?(?!#)[a-z/]/i.test(svg));
  assert.ok(svg.includes('#5EC33D'));
  assert.ok(illustration.includes(`static 'illustrations/${name}'`));
}
assert.ok(illustration.includes('aria-hidden="true"') && illustration.includes('alt=""'));
const renderer = read('../../templates/datasystem/includes/formulario_dados.html');
assert.ok(renderer.includes("{% if ilustracao_onboarding %}{% include 'datasystem/includes/illustration.html' %}{% endif %}"));
const components = read('../src/styles/retorna/_components.scss');
assert.ok(components.includes('[data-retorna-theme="dark"] .retorna-illustration--dark'));
assert.ok(!components.includes('filter: invert'));
const business = read('../../templates/datasystem/para_empresas.html');
const visibleBusiness = business.replace(/{%[\s\S]*?%}/g, '').replace(/<[^>]*>/g, ' ');
assert.ok(!/\b(API|REST|endpoint|tenant|payload|escopo|credencial|idempotência|FEFO|snapshot|override|arquitetura|PostgreSQL|Django|engine|microsserviço)\b/i.test(visibleBusiness));
const home = read('../../templates/datasystem/home.html');
assert.ok(home.includes('Como funciona para você'));
assert.ok(home.includes("url 'usuarios:para_empresas'"));
assert.ok(!home.includes('illustration.html'));
assert.ok(!business.includes('illustration.html'));
console.log('Landings, uso restrito ao onboarding, SVGs light/dark locais e linguagem pública: OK.');

await import('./validate-navigation.mjs');
