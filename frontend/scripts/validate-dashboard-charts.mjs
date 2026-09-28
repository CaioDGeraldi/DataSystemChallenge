import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { Chart as EngineChart, BasicPlatform, registerables } from 'chart.js';

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');
const source = read('../src/js/retorna/dashboard-charts.js');
assert.match(source, /from 'chart.js'/);
assert.match(read('../src/js/retorna.js'), /bindDashboardCharts\(\)/);
assert.doesNotMatch(source, /https?:|cdn|reduce\(|sort\(|empresa|fatecal|fidelidade/i);
assert.match(source, /row\[valueKey\] === null \? null : Number\(row\[valueKey\]\)/);
const template = read('../../templates/datasystem/gestor/dashboard/series.html');
for (const text of ['json_script:json_id', 'data-chart-type="line"', 'aria-labelledby', 'aria-describedby', '<summary>Ver dados</summary>']) assert.ok(template.includes(text));
assert.match(read('../../templates/datasystem/gestor/dashboard/vendas.html'), /with graficos=True/);
const fidelity = read('../../templates/datasystem/gestor/dashboard/fidelidade.html');
assert.match(fidelity, /with graficos=True/);
assert.match(fidelity, /if dashboard.niveis is not None/);
assert.match(fidelity, /if niveis_com_dados/);
assert.match(fidelity, /data-chart-type="doughnut"/);
assert.match(fidelity, /dashboard.niveis\|json_script/);
assert.match(fidelity, /id="legenda-niveis"/);
assert.match(fidelity, /data-chart-legend="legenda-niveis"/);
assert.match(fidelity, /for nivel in dashboard.niveis/);
assert.match(fidelity, /data-chart-legend-marker aria-hidden="true" hidden/);
assert.match(fidelity, /{{ nivel.nome }}/);
assert.match(fidelity, /{{ nivel.quantidade }}/);
assert.match(fidelity, /retorna-dashboard-doughnut-layout/);
const repurchase = read('../../templates/datasystem/gestor/dashboard/recompra.html');
assert.match(repurchase, /if recompra_grafico/);
assert.match(repurchase, /data-chart-type="bar"/);
assert.match(repurchase, /data-chart-palette="accent-neutral"/);
assert.match(repurchase, /periodo_recompra_dias/);
assert.match(repurchase, /Sem base suficiente/);
assert.doesNotMatch(source, /recompr|elegiveis|percentual|estorn|resgatado_em|Bronze|Prata|Ouro/);
for (const metric of ['pontos_concedidos', 'pontos_resgatados', 'custo_resgates']) {
  assert.ok(read('../../apps/dashboard/views.py').includes("('" + metric + "'"));
}
const views = read('../../apps/dashboard/views.py').split("'vendas': (")[1].split("'fidelidade': (")[0];
for (const metric of ['compras', 'volume', 'ticket']) assert.ok(views.includes("('" + metric + "'"));
assert.match(read('../src/styles/retorna/_dashboard.scss'), /@media \(forced-colors: active\)/);
const appearance = read('../src/js/retorna/appearance.js');
assert.ok(appearance.indexOf('root.dataset.retornaTheme =') < appearance.indexOf("new CustomEvent('retorna:appearance-change'"));
assert.match(appearance, /media.addEventListener\('change', apply\)/);
assert.match(appearance, /const save = \(\) => \{\s*apply\(\)/);
assert.doesNotMatch(appearance, /chart.js|Chart/);

// Exercise real binding with a Chart double: rendering needs a browser, data/state do not.
const charts = [];
class Chart {
  static register() {}
  constructor(canvas, config) { Object.assign(this, config); this.config = config; this.canvas = canvas; this.updates = []; charts.push(this); }
  update(mode) { this.updates.push(mode); }
}
const events = {};
const motion = { matches: true, addEventListener: (_, fn) => { motion.change = fn; } };
const contrast = { matches: true, addEventListener: (_, fn) => { contrast.change = fn; } };
const details = [{ open: false }, { open: false }, { open: false }];
const canvases = ['integer', 'currency', 'currency'].map((format, index) => ({
  dataset: { chartJson: String(index), chartType: 'line', chartFormat: format, chartLabel: 'Série' },
  parentElement: { hidden: true },
}));
let nodes = [];
let palette = 'light';
const document = {
  documentElement: {},
  querySelectorAll: selector => selector.startsWith('canvas') ? nodes : details,
  getElementById: () => ({ textContent: JSON.stringify([
    { mes: '2026-01-01', valor: null }, { mes: '2026-02-01', valor: '150.25' },
  ]) }),
  addEventListener: (name, fn) => { assert.ok(!events[name]); events[name] = fn; },
};
const context = {
  Chart, document, Intl,
  window: { matchMedia: query => query.includes('reduced-motion') ? motion : contrast },
  getComputedStyle: () => ({ getPropertyValue: name => palette + name }),
};

vm.createContext(context);
vm.runInContext(source.replace(/^import .*;\n/, '')
  .replace(/Chart.register\(.*\);/, '')
  .replace('export function', 'function'), context);
context.bindDashboardCharts();
assert.equal(charts.length, 0);
nodes = canvases;
context.bindDashboardCharts();
context.bindDashboardCharts();
assert.equal(charts.length, 3);
for (const chart of charts) {
  assert.equal(chart.options.animation, false);
  assert.equal(chart.data.datasets[0].data[0], null);
  assert.equal(chart.data.datasets[0].data[1], 150.25);
  assert.equal(chart.data.datasets[0].spanGaps, false);
  assert.equal(chart.data.labels[0], '01/2026');
  assert.equal(chart.canvas.parentElement.hidden, false);
}
assert.ok(details.every(detail => detail.open));
const data = charts.map(chart => chart.data.datasets[0].data);
palette = 'dark';
events['retorna:appearance-change']();
for (const [i, chart] of charts.entries()) {
  assert.equal(chart.data.datasets[0].borderColor, 'dark--primary');
  assert.equal(chart.options.scales.x.ticks.color, 'dark--text-muted');
  assert.equal(chart.options.plugins.tooltip.backgroundColor, 'dark--surface');
  assert.equal(chart.data.datasets[0].data, data[i]);
  assert.equal(chart.updates.at(-1), 'none');
}
motion.matches = false;
motion.change();
assert.equal(charts[0].options.animation.duration, 250);
motion.matches = true;
motion.change();
assert.equal(charts[0].options.animation, false);
assert.equal(charts[0].options.scales.y.ticks.precision, 0);
assert.equal(charts[1].options.scales.y.ticks.callback(150.25), new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(150.25));
assert.equal(charts[2].options.plugins.tooltip.callbacks.label({ parsed: { y: null } }), 'Sem dados');
console.log('Dashboard: ESM, contrato SSR, três séries, idempotência, tema, motion, forced colors e nulos: OK.');

const pkg = JSON.parse(read('../package.json'));
assert.ok(pkg.dependencies['chart.js'], 'Chart.js deve ser dependency normal');
const lock = JSON.parse(read('../package-lock.json'));
assert.ok(lock.packages['node_modules/chart.js']);

// The SSR loop preserves configured names, quantities and order; JS only colors markers.
const levelRows = [{ nome: 'Início', quantidade: 0 }, { nome: 'Horizonte', quantidade: 2 }];
const legendMarkers = levelRows.map(() => ({ style: {}, hidden: true }));
const legend = { querySelectorAll: selector => {
  assert.equal(selector, '[data-chart-legend-marker]');
  return legendMarkers;
} };
function assertLegend(chart) {
  assert.equal(legendMarkers.length, chart.data.labels.length);
  assert.deepEqual(Array.from(chart.data.labels), levelRows.map(row => row.nome));
  assert.deepEqual(Array.from(chart.data.datasets[0].data), levelRows.map(row => row.quantidade));
  for (const [index, marker] of legendMarkers.entries()) {
    assert.equal(marker.style.backgroundColor, chart.data.datasets[0].backgroundColor[index]);
    assert.equal(marker.hidden, false);
  }
}
// The same module handles categorical charts, zeros and decimal point volumes.
const categoryCanvases = ['bar', 'doughnut', 'line'].map((type, i) => ({
  dataset: { chartJson: 'category-' + i, chartType: type, chartFormat: i === 2 ? 'decimal' : 'integer',
    chartValue: i === 1 ? 'quantidade' : 'valor', chartLabel: 'Clientes',
    chartPalette: i === 0 ? 'accent-neutral' : undefined,
    chartLegend: i === 1 ? 'legenda-niveis' : undefined },
  parentElement: { hidden: true },
}));
document.getElementById = id => id === 'legenda-niveis' ? legend : ({ textContent: JSON.stringify(id === 'category-1'
  ? levelRows
  : id === 'category-0' ? [{ nome: 'Voltaram', valor: 18 }, { nome: 'Não voltaram', valor: 10 }]
    : [{ mes: '2026-01-01', valor: '1.2345' }, { mes: '2026-02-01', valor: 0 }]) });
nodes = categoryCanvases;
context.bindDashboardCharts();
context.bindDashboardCharts();
assert.equal(charts.length, 6);
assertLegend(charts[4]);
assert.equal(charts[3].data.labels[0], 'Voltaram');
assert.equal(charts[3].data.datasets[0].data[0], 18);
assert.equal(charts[4].data.labels[1], 'Horizonte');
assert.equal(charts[4].data.datasets[0].data[0], 0);
assert.equal(Object.keys(charts[4].options.scales).length, 0);
assert.equal(charts[4].options.plugins.tooltip.callbacks.label({ parsed: 2, label: 'Horizonte' }), 'Horizonte: 2');
assert.equal(charts[5].options.scales.y.ticks.callback(1.2345), '1,2345');
assert.equal(charts[5].data.datasets[0].data[1], 0);
palette = 'light';
events['retorna:appearance-change']();
assert.equal(charts[4].data.datasets[0].backgroundColor[0], 'light--primary');
assert.equal(charts[4].data.datasets[0].backgroundColor[1], 'light--success');
assert.equal(charts[4].data.datasets[0].borderColor, 'light--surface');
assertLegend(charts[4]);
assert.equal(charts[3].options.animation, false);
console.log('Fidelidade: barras, linhas decimais, doughnut categórico, tema, zero, legenda SSR e estados sem base: OK.');

const clients = read('../../templates/datasystem/gestor/dashboard/clientes.html');
for (const text of ['if atividade_clientes_grafico', 'if ranking_grafico',
  'atividade_clientes_grafico|json_script', 'ranking_grafico|json_script',
  'aria-describedby="resumo-atividade-clientes"', 'aria-describedby="resumo-ranking"',
  'periodo_cliente_ativo_dias', 'for cliente in dashboard.ranking', '<summary>Ver dados</summary>']) {
  assert.ok(clients.includes(text));
}
assert.equal((clients.match(/data-chart-axis="y"/g) ?? []).length, 2);
assert.doesNotMatch(clients, /_meses|cliente_id|\.pk|cpf/i);
assert.doesNotMatch(source, /clientes_ativos|clientes_inativos|clientes_no_escopo|ranking|\.sort\(|\.filter\(|\.reduce\(/);
const clientRows = {
  activity: [{ nome: 'Ativos', valor: 32 }, { nome: 'Inativos', valor: 4 }],
  ranking: [{ nome: 'Zélia com nome muito longo de apresentação', pontos: '8950.1234' },
    { nome: 'Ana', pontos: '6720.0000' }],
  empty: [],
};
const clientCanvases = Object.keys(clientRows).map(key => ({
  dataset: { chartJson: key, chartType: 'bar', chartAxis: 'y', chartLabelLimit: '20',
    chartValue: key === 'ranking' ? 'pontos' : 'valor',
    chartFormat: key === 'ranking' ? 'decimal' : 'integer', chartLabel: key === 'ranking' ? 'Pontos concedidos' : 'Clientes' },
  parentElement: { hidden: true },
}));
document.getElementById = id => id === 'legenda-niveis' ? legend : ({ textContent: JSON.stringify(clientRows[id]) });
nodes = clientCanvases;
context.bindDashboardCharts();
context.bindDashboardCharts();
assert.equal(charts.length, 8);
assert.equal(clientCanvases[2].parentElement.hidden, true);
for (const [index, key] of ['activity', 'ranking'].entries()) {
  const chart = charts[6 + index];
  assert.equal(chart.options.indexAxis, 'y');
  assert.equal(chart.options.scales.x.beginAtZero, true);
  assert.equal(chart.options.scales.y.ticks.autoSkip, false);
  assert.deepEqual(Array.from(chart.data.labels), clientRows[key].map(row => row.nome));
  assert.deepEqual(Array.from(chart.data.datasets[0].data), clientRows[key].map(row => Number(row[index ? 'pontos' : 'valor'])));
  assert.equal(chart.options.animation, false);
}
assert.equal(charts[6].options.scales.x.ticks.precision, 0);
assert.equal(charts[7].options.scales.x.ticks.callback(8950.1234), '8.950,1234');
assert.equal(charts[7].options.plugins.tooltip.callbacks.label({ parsed: { x: 8950.1234 }, dataset: { label: 'Pontos concedidos' } }), 'Pontos concedidos: 8.950,1234');
const tick = charts[7].options.scales.y.ticks.callback;
assert.equal(tick.call({ getLabelForValue: () => clientRows.ranking[0].nome }, 0), clientRows.ranking[0].nome.slice(0, 20) + '…');
assert.equal(tick.call({ getLabelForValue: () => 'Ana' }, 1), 'Ana');
for (const theme of ['dark', 'light']) {
  palette = theme;
  events['retorna:appearance-change']();
  assertLegend(charts[4]);
  const bars = charts[3].data.datasets[0];
  assert.deepEqual(Array.from(bars.backgroundColor), [theme + '--accent', theme + '--text-muted']);
  assert.deepEqual(Array.from(bars.borderColor), [theme + '--success', theme + '--text-muted']);
  assert.equal(bars.hoverBackgroundColor, bars.backgroundColor);
  assert.equal(bars.hoverBorderColor, bars.borderColor);
  for (const chart of charts.slice(6)) {
    assert.deepEqual(Array.from(chart.data.datasets[0].backgroundColor), Array.from(chart.data.labels, () => theme + '--accent'));
    assert.deepEqual(Array.from(chart.data.datasets[0].borderColor), Array.from(chart.data.labels, () => theme + '--success'));
    assert.deepEqual(Array.from(chart.data.datasets[0].hoverBackgroundColor), Array.from(chart.data.labels, () => theme + '--accent'));
    assert.deepEqual(Array.from(chart.data.datasets[0].hoverBorderColor), Array.from(chart.data.labels, () => theme + '--success'));
    assert.equal(chart.options.scales.x.grid.color, theme + '--border');
    assert.equal(chart.options.scales.y.ticks.color, theme + '--text-muted');
  }
}
motion.matches = false;
motion.change();
assert.equal(charts[7].options.animation.duration, 250);
motion.matches = true;
motion.change();
assert.equal(charts[7].options.animation, false);
details.forEach(detail => { detail.open = false; });
contrast.change();
assert.ok(details.every(detail => detail.open));
console.log('Clientes: barras horizontais, ordem e valores SSR, decimais, nomes longos, vazio, tema, motion e forced colors: OK.');


// Verify actual BarElement options: a dataset-only double misses Chart.js shared
// options retaining the initial gray after colors are applied with update('none').
EngineChart.register(...registerables);
const renderedCharts = [];
class RenderChart extends EngineChart {
  constructor(canvas, config) {
    super(canvas, { ...config, platform: BasicPlatform,
      options: { ...config.options, responsive: false, animation: false } });
    renderedCharts.push(this);
  }
}
const renderEvents = {};
const renderRows = { ...clientRows, comparison: [
  { nome: 'Voltaram', valor: 18 }, { nome: 'Não voltaram', valor: 10 },
] };
const renderCanvases = [...clientCanvases.slice(0, 2), {
  dataset: { chartJson: 'comparison', chartType: 'bar', chartPalette: 'accent-neutral' },
}].map(original => {
  const canvas = { dataset: original.dataset, parentElement: { hidden: true }, width: 640, height: 480 };
  const ctx = new Proxy({ canvas, measureText: text => ({ width: String(text).length * 7 }) }, {
    get: (target, key) => key in target ? target[key] : () => {},
  });
  canvas.getContext = () => ctx;
  return canvas;
});
let renderTheme = 'light';
const renderTokens = {
  light: { '--accent': '#5ec33d', '--success': '#25623c', '--text-muted': '#58657a' },
  dark: { '--accent': '#5ec33d', '--success': '#a1d8ad', '--text-muted': '#b4c1d2' },
};
const renderContext = {
  Chart: RenderChart, Intl,
  document: {
    documentElement: {},
    querySelectorAll: selector => selector.startsWith('canvas') ? renderCanvases : [],
    getElementById: id => ({ textContent: JSON.stringify(renderRows[id]) }),
    addEventListener: (name, fn) => { renderEvents[name] = fn; },
  },
  window: { matchMedia: () => ({ matches: false, addEventListener() {} }) },
  getComputedStyle: () => ({ getPropertyValue: name => renderTokens[renderTheme][name] ?? '#ffffff' }),
};
vm.createContext(renderContext);
vm.runInContext(source.replace(/^import .*;\n/, '')
  .replace(/Chart.register\(.*\);/, '').replace('export function', 'function'), renderContext);
renderContext.bindDashboardCharts();
assert.equal(renderedCharts.length, 3);
try {
  for (const [phase, theme] of ['light', 'dark', 'light'].entries()) {
    renderTheme = theme;
    if (phase > 0) {
      renderEvents['retorna:appearance-change']();
    }
    for (const [chartIndex, chart] of renderedCharts.entries()) {
      const meta = chart.getDatasetMeta(0);
      for (const [index, bar] of meta.data.entries()) {
        const expected = renderTokens[theme][chartIndex === 2 && index === 1 ? '--text-muted' : '--accent'];
        assert.equal(bar.options.backgroundColor, expected, 'Base fill must be correct before hover');
        assert.equal(bar.options.borderColor, renderTokens[theme][chartIndex === 2 && index === 1 ? '--text-muted' : '--success']);
        meta.controller.setHoverStyle(bar, 0, index);
        assert.equal(bar.options.backgroundColor, expected);
        meta.controller.removeHoverStyle(bar, 0, index);
        assert.equal(bar.options.backgroundColor, expected, 'Base fill must persist after hover');
      }
    }
  }
} finally {
  renderedCharts.forEach(chart => chart.destroy());
}
console.log('Chart.js real: fill verde antes/depois do hover em Clientes, tema em runtime e exceção neutra da Recompra: OK.');
