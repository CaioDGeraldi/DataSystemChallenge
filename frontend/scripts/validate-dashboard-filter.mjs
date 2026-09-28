import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { bindDashboardFilter } from '../src/js/retorna/dashboard-filter.js';

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');
const template = read('../../templates/datasystem/gestor/dashboard/base.html');
assert.match(template, /<form[^>]*method="get"[^>]*data-store-search/);
assert.match(template, /<button class="button" type="submit">Aplicar filtro<\/button>/);
assert.match(template, /dashboard_periodos.items/);
assert.match(template, /type="hidden" name="{{ parametro }}" value="{{ meses }}"/);
assert.match(read('../src/js/retorna.js'), /bindDashboardFilter\(\)/);
const source = read('../src/js/retorna/dashboard-filter.js');
assert.doesNotMatch(source, /fetch\(|XMLHttpRequest|scrollRestoration|location.search/);
const storage = new Map();
const key = path => 'retorna.dashboard.scroll.v1:' + path;
function page({ path = '/dashboard/vendas/', ready = 'complete', failure, native = true } = {}) {
  const handlers = {}, events = {}, frames = [], scrolls = [], submitted = [];
  const select = { value: '', addEventListener(type, fn) {
    assert.equal(handlers[type], undefined); handlers[type] = fn;
  } };
  const button = { hidden: false };
  const hidden = { compras_meses: '3', volume_meses: '6', ticket_meses: '12', extra: 'preservado' };
  const form = {
    dataset: {},
    querySelector: selector => selector.startsWith('select') ? select : button,
    requestSubmit: native ? () => {
      assert.equal(storage.get(key(path)), '640');
      submitted.push({ loja: select.value, ...hidden });
    } : undefined,
  };
  globalThis.document = { readyState: ready, querySelector: () => form };
  globalThis.window = {
    location: { pathname: path }, scrollY: 640,
    requestAnimationFrame: fn => frames.push(fn),
    addEventListener: (type, fn, options) => { events[type] = fn; assert.equal(options.once, true); },
    scrollTo: options => scrolls.push(options),
    get sessionStorage() {
      if (failure === 'access') throw Error('SecurityError');
      return {
        getItem: k => { if (failure === 'read') throw Error(); return storage.get(k) ?? null; },
        setItem: (k, value) => { if (failure === 'write') throw Error(); storage.set(k, value); },
        removeItem: k => { if (failure === 'remove') throw Error(); storage.delete(k); },
      };
    },
  };
  return { form, select, button, handlers, events, frames, scrolls, submitted };
}

globalThis.document = { querySelector: () => null };
bindDashboardFilter();
let p = page();
assert.equal(p.button.hidden, false);
bindDashboardFilter();
bindDashboardFilter();
assert.equal(p.button.hidden, true);
assert.equal(p.frames.length, 1);
p.handlers.change();
assert.equal(p.submitted.length, 0);
p.select.value = '2';
p.handlers.change();
p.handlers.change();
assert.equal(p.submitted.length, 1);
assert.deepEqual(p.submitted[0], {
  loja: '2', compras_meses: '3', volume_meses: '6', ticket_meses: '12', extra: 'preservado',
});
assert.equal(storage.get(key('/dashboard/vendas/')), '640');

// Another section must not consume Vendas' scroll.
p = page({ path: '/dashboard/clientes/' });
bindDashboardFilter(); p.frames[0]();
assert.equal(p.scrolls.length, 0);
assert.equal(storage.get(key('/dashboard/vendas/')), '640');
p = page({ ready: 'interactive' });
bindDashboardFilter();
assert.equal(p.frames.length, 0);
p.events.pageshow();
p.frames[0]();
assert.deepEqual(p.scrolls, [{ top: 640, left: 0, behavior: 'instant' }]);
assert.equal(storage.has(key('/dashboard/vendas/')), false);

for (const failure of ['access', 'read', 'write', 'remove']) {
  storage.clear();
  storage.set(key('/dashboard/vendas/'), '120');
  p = page({ failure });
  let submissions = 0;
  p.form.requestSubmit = () => { submissions++; };
  bindDashboardFilter();
  p.frames[0]();
  p.select.value = '1'; p.handlers.change();
  assert.equal(submissions, 1);
}
for (const value of ['invalid', '-1', 'Infinity']) {
  storage.set(key('/dashboard/vendas/'), value);
  p = page(); bindDashboardFilter(); p.frames[0]();
  assert.equal(p.scrolls.length, 0);
  assert.equal(storage.has(key('/dashboard/vendas/')), false);
}
p = page({ native: false });
bindDashboardFilter();
assert.equal(p.button.hidden, false);
assert.equal(p.handlers.change, undefined);
delete globalThis.window;
delete globalThis.document;
console.log('Filtro Dashboard: GET, períodos/hidden preservados, seleção distinta, fallback, scroll por seção, storage indisponível e idempotência: OK.');
