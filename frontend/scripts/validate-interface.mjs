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
  globalThis.CustomEvent = class { constructor(type, options) { this.type = type; this.detail = options.detail; } };
  let events = 0;
  globalThis.document = { documentElement: { dataset: {} }, querySelector: () => null,
    dispatchEvent(event) {
      assert.equal(event.type, 'retorna:appearance-change');
      assert.equal(event.detail.theme, document.documentElement.dataset.retornaTheme);
      events++;
    },
  };
  globalThis.window = { localStorage: { getItem: () => JSON.stringify({ theme }) }, matchMedia: () => media };
  bindAppearance();
  assert.equal(document.documentElement.dataset.retornaTheme, effectiveTheme(theme, false));
  media.matches = true;
  onChange();
  assert.equal(document.documentElement.dataset.retornaTheme, effectiveTheme(theme, true));
  assert.equal(events, 2);
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


// Lightweight DOM doubles exercise the real combobox mouse/keyboard handlers.
const { bindStoreSearch } = await import('../src/js/retorna/store-search.js');
const { bindDashboardFilter } = await import('../src/js/retorna/dashboard-filter.js');
class StoreElement {
  constructor() { this.children = []; this.attrs = {}; this.dataset = {}; this.events = {}; this.value = ''; this.hidden = false; this.textContent = ''; }
  setAttribute(key, value) { this.attrs[key] = value; }
  removeAttribute(key) { delete this.attrs[key]; }
  addEventListener(type, handler) { (this.events[type] ??= []).push(handler); }
  append(...nodes) { this.children.push(...nodes); }
  before(node) { this.enhancement = node; }
  contains(node) { return this === node || this.children.some(child => child.contains(node)); }
  scrollIntoView() {}
  dispatchEvent(event) { for (const handler of this.events[event.type] ?? []) handler(event); }
  fire(type, extras = {}) {
    const event = { type, target: this, preventDefault() { this.defaultPrevented = true; }, ...extras };
    this.dispatchEvent(event); return event;
  }
}
const originalOptions = [
  { value: '', textContent: 'Todas as lojas' },
  { value: '1', textContent: 'Calçados Centro — São Paulo' },
  { value: '2', textContent: 'Jardim Aurora — Araras' },
  { value: '3', textContent: 'Outlet — Limeira' },
];
const dashboard = read('../../templates/datasystem/gestor/dashboard/base.html');
assert.ok(dashboard.includes('<select id="dashboard-loja" name="loja">'));
assert.ok(dashboard.includes('<label for="dashboard-loja">Loja</label>'));
assert.ok(!dashboard.includes('role="combobox"') && !dashboard.includes('Buscar loja'));
assert.ok(!/históric[oa]s?|Lojas permitidas|lojas autorizadas/i.test(dashboard));
assert.ok(read('../../apps/fidelidade/seed_fatecalcados.py').includes("NOME_EMPRESA = 'FATECalçados'"));
for (const selected of ['', '2']) {
  const doc = new StoreElement();
  doc.createElement = () => new StoreElement();
  globalThis.document = doc;
  const root = new StoreElement(), select = new StoreElement(), label = new StoreElement();
  select.options = [...originalOptions]; select.id = 'dashboard-loja'; select.name = 'loja'; select.value = selected;
  label.htmlFor = select.id;
  doc.querySelector = () => root;
  root.querySelector = selector => selector === 'select[name="loja"]' ? select : label;
  let changes = 0, submits = 0;
  select.addEventListener('change', () => changes++);
  root.addEventListener('submit', () => submits++);
  assert.equal(select.hidden, false);
  assert.equal(select.enhancement, undefined);
  bindStoreSearch();
  const control = select.enhancement;
  bindStoreSearch(); assert.equal(select.enhancement, control);
  const [input, popup] = control.children, [list, status] = popup.children;
  const shown = () => list.children.filter(option => !option.hidden).map(option => option.textContent);
  const currentText = originalOptions.find(option => option.value === selected).textContent;
  assert.equal(select.name, 'loja');
  assert.deepEqual(select.options, originalOptions);
  assert.equal(select.hidden, true);
  assert.equal(input.value, currentText);
  assert.equal(label.htmlFor, input.id);
  assert.equal(input.attrs.role, 'combobox');
  assert.equal(input.attrs['aria-autocomplete'], 'list');
  assert.equal(input.attrs['aria-controls'], list.id);
  assert.equal(input.attrs['aria-expanded'], 'false');
  assert.equal(list.attrs.role, 'listbox');
  assert.equal(status.attrs.role, 'status');
  assert.equal(status.attrs['aria-live'], 'polite');
  assert.ok(list.children.every(option => option.attrs.role === 'option'));
  doc.activeElement = input;
  input.fire('focus');
  assert.equal(popup.hidden, false);
  assert.equal(input.attrs['aria-expanded'], 'true');
  assert.deepEqual(shown(), originalOptions.map(option => option.textContent));
  assert.equal(list.children[Number(selected)].attrs['aria-selected'], 'true');
  for (const query of ['CALÇADOS', 'calcados', 'sao paulo', 'Calçados Centro — São Paulo']) {
    input.value = query; input.fire('input');
    assert.deepEqual(shown(), ['Todas as lojas', originalOptions[1].textContent]);
    assert.equal(select.value, selected);
    assert.equal(status.textContent, '');
    assert.equal(input.attrs['aria-activedescendant'], undefined);
    assert.equal(doc.activeElement, input);
  }
  input.value = 'inexistente'; input.fire('input');
  assert.deepEqual(shown(), ['Todas as lojas']);
  assert.equal(status.textContent, 'Nenhuma loja encontrada.');
  assert.equal(status.attrs.role, 'status');
  assert.equal(input.fire('keydown', { key: 'Enter' }).defaultPrevented, true);
  assert.equal(select.value, selected);
  input.value = ''; input.fire('input');
  assert.deepEqual(shown(), originalOptions.map(option => option.textContent));
  assert.equal(status.textContent, '');
  input.fire('keydown', { key: 'ArrowDown' });
  assert.equal(input.attrs['aria-activedescendant'], list.children[0].id);
  input.fire('keydown', { key: 'ArrowDown' });
  assert.equal(input.attrs['aria-activedescendant'], list.children[1].id);
  input.fire('keydown', { key: 'ArrowUp' });
  assert.equal(input.attrs['aria-activedescendant'], list.children[0].id);
  input.fire('keydown', { key: 'ArrowDown' });
  input.fire('keydown', { key: 'Enter' });
  assert.equal(select.value, '1');
  assert.equal(input.value, originalOptions[1].textContent);
  assert.equal(popup.hidden, true);
  assert.equal(input.attrs['aria-activedescendant'], undefined);
  assert.equal(changes, 1); assert.equal(submits, 0);
  input.fire('keydown', { key: 'ArrowDown' });
  assert.equal(popup.hidden, false);
  assert.equal(input.attrs['aria-activedescendant'], list.children[2].id);
  input.value = 'jardim'; input.fire('input');
  assert.equal(select.value, '1');
  input.fire('keydown', { key: 'Escape' });
  assert.equal(input.value, originalOptions[1].textContent);
  assert.equal(popup.hidden, true);
  input.fire('click'); input.value = 'araras'; input.fire('input');
  assert.deepEqual(shown(), ['Todas as lojas', originalOptions[2].textContent]);
  assert.equal(list.children[2].fire('pointerdown').defaultPrevented, true);
  list.children[2].fire('click');
  assert.equal(select.value, '2');
  assert.equal(input.value, originalOptions[2].textContent);
  assert.equal(popup.hidden, true);
  input.fire('click'); input.value = 'abandonar'; input.fire('input');
  doc.fire('click', { target: new StoreElement() });
  assert.equal(input.value, originalOptions[2].textContent);
  assert.equal(select.value, '2'); assert.equal(popup.hidden, true);
  input.fire('click'); input.value = 'outra busca'; input.fire('input');
  assert.ok(!input.fire('keydown', { key: 'Tab' }).defaultPrevented);
  assert.equal(input.value, originalOptions[2].textContent);
  assert.equal(popup.hidden, true);
  input.fire('focus'); input.value = 'outlet'; input.fire('input'); input.fire('blur');
  assert.equal(input.value, originalOptions[2].textContent);
  input.fire('click'); list.children[0].fire('click');
  assert.equal(select.value, ''); assert.equal(input.value, 'Todas as lojas');
  assert.equal(submits, 0);
  assert.equal(input.fire('keydown', { key: 'Enter' }).defaultPrevented, true);
  assert.deepEqual(select.options, originalOptions);

  // Integrate the real combobox keyboard contract with Dashboard auto-submit.
  const button = new StoreElement();
  root.querySelector = selector => selector === 'select[name="loja"]' ? select
    : selector === 'button[type="submit"]' ? button : label;
  root.requestSubmit = () => root.fire('submit');
  globalThis.window = {
    location: { pathname: '/dashboard/vendas/' }, scrollY: 240,
    sessionStorage: { getItem: () => null, setItem() {} },
    addEventListener() {},
  };
  bindDashboardFilter();
  bindDashboardFilter();
  assert.equal(button.hidden, true);
  input.fire('click');
  input.fire('keydown', { key: 'ArrowDown' });
  assert.equal(select.value, '');
  assert.equal(submits, 0);
  input.fire('keydown', { key: 'Enter' });
  assert.equal(select.value, '1');
  assert.equal(submits, 1);
  assert.equal(popup.hidden, true);
  input.fire('click');
  input.fire('keydown', { key: 'Enter' });
  assert.equal(submits, 1);
  input.fire('click');
  input.fire('keydown', { key: 'ArrowDown' });
  input.fire('keydown', { key: 'Escape' });
  assert.equal(select.value, '1');
  assert.equal(submits, 1);
  delete globalThis.window;
}
delete globalThis.document;
console.log('Combobox de lojas: fallback, seleção inicial, pesquisa, ARIA, mouse, teclado e abandono: OK (DOM simulado).');
