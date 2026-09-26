export function normalizeSearch(value) {
  return value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR').trim();
}
export function matchesNavigation(label, query) {
  return normalizeSearch(label).includes(normalizeSearch(query));
}
export function searchShortcut(event) {
  return !event.defaultPrevented && !event.isComposing && event.altKey && !event.ctrlKey && !event.metaKey && !event.shiftKey && event.key.toLowerCase() === 'k';
}
export function bindNavigationSearch() {
  const root = document.querySelector('[data-navigation-search]');
  if (!root || root.dataset.bound) return;
  root.dataset.bound = 'true';
  const trigger = root.querySelector('[data-navigation-search-trigger]');
  const panel = root.querySelector('[data-navigation-search-panel]');
  const input = root.querySelector('[data-navigation-search-input]');
  const status = root.querySelector('[data-navigation-search-status]');
  const items = [...root.querySelectorAll('[data-navigation-search-item]')];
  let visible = [];
  const filter = () => {
    visible = [];
    for (const item of items) {
      const link = item.querySelector('a');
      item.hidden = !matchesNavigation(link.textContent, input.value);
      if (!item.hidden) visible.push(link);
    }
    status.textContent = visible.length ? `${visible.length} destino(s) encontrado(s).` : 'Nenhum destino encontrado.';
  };
  const open = () => { panel.hidden = false; trigger.setAttribute('aria-expanded', 'true'); filter(); input.focus(); };
  const close = (restore = false) => { panel.hidden = true; trigger.setAttribute('aria-expanded', 'false'); if (restore) trigger.focus(); };
  root.hidden = false;
  trigger.addEventListener('click', () => panel.hidden ? open() : close(true));
  input.addEventListener('input', filter);
  root.addEventListener('keydown', event => {
    if (panel.hidden) return;
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(true); }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const current = visible.indexOf(document.activeElement);
      const next = current < 0 ? (event.key === 'ArrowDown' ? 0 : visible.length - 1) : (current + (event.key === 'ArrowDown' ? 1 : -1) + visible.length) % visible.length;
      visible[next]?.focus();
    }
    if (event.key === 'Enter' && event.target === input) { event.preventDefault(); visible[0]?.click(); }
  });
  document.addEventListener('keydown', event => {
    if (!searchShortcut(event) || document.querySelector('dialog[open]')) return;
    if (event.target !== input && event.target.closest?.('input, textarea, select, [contenteditable]:not([contenteditable="false"])')) return;
    event.preventDefault(); open();
  });
  document.addEventListener('click', event => { if (!root.contains(event.target)) close(); });
  root.addEventListener('focusout', event => { if (!root.contains(event.relatedTarget)) close(); });
}
