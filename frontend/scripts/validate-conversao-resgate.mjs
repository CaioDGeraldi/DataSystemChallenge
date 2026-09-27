import assert from 'node:assert/strict';
import { decimalInteiro, moeda, linhasConversao, bindConversaoResgate } from '../src/js/retorna/conversao-resgate.js';

assert.equal(decimalInteiro('0,05', 2), 5n);
assert.equal(decimalInteiro('0.005', 2), null);
assert.equal(decimalInteiro('-1', 0), null);
assert.equal(moeda(5n), 'R$ 0,05');
assert.equal(moeda(100005n), 'R$ 1.000,05');
assert.deepEqual(linhasConversao(120n, 50n, 5n, 1n)[0], { pontos: 620n, desconto: 3100n });
assert.equal(linhasConversao(120n, 50n, 5n, 0n).length, 10);
assert.equal(linhasConversao(100n, 100n, 5n, 999999999999999999n)[9].desconto, 5000000000000000000000n);

class Elemento {
  children = [];
  handlers = {};
  addEventListener(nome, funcao) { this.handlers[nome] = funcao; }
  append(el) { this.children.push(el); }
  replaceChildren() { this.children = []; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  disparar(evento) { this.handlers[evento](); }
}
const elementos = Object.fromEntries(['preview', 'limite', 'modal', 'linhas', 'pagina', 'anterior', 'proxima', 'abrir', 'fechar'].map(nome => [nome, new Elemento()]));
const campos = Object.fromEntries(Object.entries({resgate_minimo_pontos: '100', incremento_resgate_pontos: '100', valor_monetario_por_ponto: '0.05', limite_resgate_percentual: '50.0000'}).map(([nome, value]) => [nome, Object.assign(new Elemento(), {value})]));
const bloco = { closest: () => ({elements: campos}), querySelector: seletor => elementos[seletor.slice(14, -1)] };
const root = {querySelectorAll: () => [bloco], createElement: () => new Elemento()};
bindConversaoResgate(root);
assert.equal(elementos.preview.textContent, '100 pontos = R$ 5,00 de desconto');
assert.match(elementos.limite.textContent, /R\$ 50,00/);
assert.equal(elementos.linhas.children.length, 10);
assert.equal(elementos.anterior.disabled, true);
elementos.abrir.disparar('click');
assert.equal(elementos.modal.open, true);
elementos.proxima.disparar('click');
assert.equal(elementos.pagina.textContent, 'Página 2');
assert.equal(elementos.linhas.children[0].children[0].textContent, '1.100');
campos.valor_monetario_por_ponto.value = '0.07';
campos.valor_monetario_por_ponto.disparar('input');
assert.equal(elementos.pagina.textContent, 'Página 1');
assert.match(elementos.preview.textContent, /R\$ 7,00/);
assert.equal(elementos.linhas.children[0].children[1].textContent, 'R$ 7,00');
campos.incremento_resgate_pontos.value = '';
campos.incremento_resgate_pontos.disparar('input');
assert.equal(elementos.linhas.children.length, 0);
assert.equal(elementos.proxima.disabled, true);
elementos.fechar.disparar('click');
assert.equal(elementos.modal.open, false);
console.log('Conversão de Resgate: cálculo inteiro, preview, modal e paginação OK.');
