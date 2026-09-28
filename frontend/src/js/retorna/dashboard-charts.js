import { Chart, LineController, LineElement, PointElement, CategoryScale, LinearScale, Tooltip, BarController, BarElement, DoughnutController, ArcElement } from 'chart.js';

Chart.register(LineController, LineElement, PointElement, CategoryScale, LinearScale, Tooltip, BarController, BarElement, DoughnutController, ArcElement);
const instances = new Map();
let bound = false;

function applyColors(chart) {
  const styles = getComputedStyle(document.documentElement);
  const token = name => styles.getPropertyValue(name).trim();
  const dataset = chart.data.datasets[0];
  const circular = chart.config.type === 'doughnut';
  const palette = ['--primary', '--success', '--warning', '--danger', '--text-muted'].map(token);
  dataset.borderColor = token(circular ? '--surface' : '--primary');
  dataset.backgroundColor = circular
    ? chart.data.labels.map((_, index) => palette[index % palette.length]) : token('--primary');
  if (chart.config.type === 'bar') {
    // Indexable colors avoid stale shared element options on update('none').
    // The optional neutral category is presentation-only.
    const neutral = chart.canvas.dataset.chartPalette === 'accent-neutral';
    dataset.backgroundColor = chart.data.labels.map((_, index) =>
      token(neutral && index === 1 ? '--text-muted' : '--accent'));
    dataset.borderColor = chart.data.labels.map((_, index) =>
      token(neutral && index === 1 ? '--text-muted' : '--success'));
    dataset.hoverBackgroundColor = dataset.backgroundColor;
    dataset.hoverBorderColor = dataset.borderColor;
  }
  if (circular && chart.canvas.dataset.chartLegend) {
    const legend = document.getElementById(chart.canvas.dataset.chartLegend);
    legend?.querySelectorAll('[data-chart-legend-marker]').forEach((marker, index) => {
      marker.style.backgroundColor = dataset.backgroundColor[index];
      marker.hidden = false;
    });
  }
  dataset.pointBackgroundColor = token('--surface');
  dataset.pointBorderColor = token('--primary');
  for (const axis of Object.values(chart.options.scales ?? {})) {
    axis.ticks.color = token('--text-muted');
    axis.grid.color = token('--border');
    axis.border.color = token('--border');
  }
  Object.assign(chart.options.plugins.tooltip, {
    backgroundColor: token('--surface'),
    titleColor: token('--text'),
    bodyColor: token('--text'),
    borderColor: token('--control-border'),
    borderWidth: 1,
  });
}

export function bindDashboardCharts() {
  const canvases = document.querySelectorAll('canvas[data-chart-type][data-chart-json]');
  if (!canvases.length) return;
  const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const contrast = window.matchMedia('(forced-colors: active)');
  for (const canvas of canvases) {
    if (instances.has(canvas)) continue;
    const source = document.getElementById(canvas.dataset.chartJson);
    if (!source) continue;
    // Server order and values are authoritative; only rendering representation changes.
    const rows = JSON.parse(source.textContent);
    if (!rows.length) continue;
    const type = canvas.dataset.chartType;
    const horizontal = canvas.dataset.chartAxis === 'y';
    const labelLimit = Number(canvas.dataset.chartLabelLimit);
    const circular = type === 'doughnut';
    const currency = canvas.dataset.chartFormat === 'currency';
    const integer = canvas.dataset.chartFormat === 'integer';
    const valueKey = canvas.dataset.chartValue ?? 'valor';
    const format = new Intl.NumberFormat('pt-BR', currency
      ? { style: 'currency', currency: 'BRL' } : { maximumFractionDigits: integer ? 0 : 4 });
    const wrapper = canvas.parentElement;
    wrapper.hidden = false;
    const chart = new Chart(canvas, {
      type: canvas.dataset.chartType,
      data: {
        labels: rows.map(row => type === 'line'
          ? row.mes.slice(5, 7) + '/' + row.mes.slice(0, 4) : row.nome),
        datasets: [{
          label: canvas.dataset.chartLabel,
          data: rows.map(row => row[valueKey] === null ? null : Number(row[valueKey])),
          spanGaps: false, borderWidth: 2, pointRadius: 3, pointHoverRadius: 5,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        indexAxis: horizontal ? 'y' : 'x',
        animation: motion.matches ? false : { duration: 250 },
        scales: circular ? {} : {
          [horizontal ? 'y' : 'x']: {
            ticks: {
              maxRotation: 0, autoSkip: !horizontal,
              ...(labelLimit ? { callback(value) {
                const label = this.getLabelForValue(value);
                return label.length > labelLimit ? label.slice(0, labelLimit) + '…' : label;
              } } : {}),
            },
            grid: {}, border: {},
          },
          [horizontal ? 'x' : 'y']: {
            beginAtZero: true,
            ticks: { ...(integer ? { precision: 0 } : {}), callback: value => format.format(value) },
            grid: {}, border: {},
          },
        },
        plugins: {
          tooltip: {
            callbacks: {
              label: context => {
                const value = circular ? context.parsed : context.parsed[horizontal ? 'x' : 'y'];
                return value === null ? 'Sem dados'
                  : (circular ? context.label : context.dataset.label) + ': ' + format.format(value);
              },
            },
          },
        },
      },
    });
    instances.set(canvas, chart);
    applyColors(chart);
    chart.update('none');
  }
  if (bound) return;
  bound = true;
  document.addEventListener('retorna:appearance-change', () => {
    for (const chart of instances.values()) {
      applyColors(chart);
      chart.update('none');
    }
  });
  motion.addEventListener('change', () => {
    for (const chart of instances.values()) {
      chart.options.animation = motion.matches ? false : { duration: 250 };
      chart.update('none');
    }
  });
  const showText = () => {
    if (contrast.matches) {
      document.querySelectorAll('.retorna-dashboard-chart-data').forEach(details => { details.open = true; });
    }
  };
  contrast.addEventListener('change', showText);
  showText();
}
