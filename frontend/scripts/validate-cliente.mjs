import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const css = readFileSync(new URL('../src/styles/retorna/_cliente.scss', import.meta.url), 'utf8');
for (const contrato of ['env(safe-area-inset-bottom, 0px)', 'position: fixed', 'position: static', 'min-width: 48rem', 'min-height: 56px', 'corner-shape: squircle', 'border-radius: 1.25rem', 'forced-colors', "a[aria-current='page']"]) {
  assert.ok(css.includes(contrato), contrato);
}
assert.ok(css.includes('calc(7rem + env(safe-area-inset-bottom, 0px))'));
assert.ok(readFileSync(new URL('../src/styles/retorna.scss', import.meta.url), 'utf8').includes('@use "retorna/cliente"'));
console.log('Cliente: navegação responsiva, safe area, alvos de toque, fallback de cantos e forced colors OK.');
