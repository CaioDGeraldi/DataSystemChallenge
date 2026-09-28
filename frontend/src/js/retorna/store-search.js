import { normalizeSearch } from './navigation-search.js';

export function bindStoreSearch() {
  const root = document.querySelector('[data-store-search]');
  if (!root || root.dataset.bound) return;
  const select = root.querySelector('select[name="loja"]');
  const label = root.querySelector('label[for="dashboard-loja"]');
  if (!select || !label) return;
  const options = [...select.options];
  const control = document.createElement('div');
  control.className = 'retorna-store-combobox';
  const input = document.createElement('input');
  input.id = `${select.id}-combobox`;
  input.type = 'text';
  input.autocomplete = 'off';
  input.placeholder = 'Buscar por nome ou cidade';
  input.setAttribute('role', 'combobox');
  input.setAttribute('aria-autocomplete', 'list');
  input.setAttribute('aria-expanded', 'false');
  const popup = document.createElement('div');
  popup.className = 'retorna-store-popup';
  popup.hidden = true;
  const list = document.createElement('div');
  list.id = `${select.id}-suggestions`;
  list.setAttribute('role', 'listbox');
  list.setAttribute('aria-label', 'Lojas');
  input.setAttribute('aria-controls', list.id);
  const status = document.createElement('p');
  status.className = 'helptext';
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
  let visible = [], active = -1;
  const selectedText = () => options.find(option => option.value === select.value)?.textContent ?? '';
  const close = () => {
    popup.hidden = true;
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
    input.value = selectedText();
    status.textContent = '';
    active = -1;
  };
  const choose = option => {
    select.value = option.value;
    select.dispatchEvent(new Event('change', { bubbles: true }));
    close();
  };
  const entries = options.map((option, index) => {
    const node = document.createElement('div');
    node.id = `${list.id}-${index}`;
    node.setAttribute('role', 'option');
    node.textContent = option.textContent;
    node.addEventListener('pointerdown', event => event.preventDefault());
    node.addEventListener('click', () => choose(option));
    list.append(node);
    return { option, node, search: normalizeSearch(option.textContent) };
  });
  const highlight = index => {
    active = index;
    for (const entry of entries) entry.node.dataset.active = String(entry === visible[active]);
    const node = visible[active]?.node;
    if (node) {
      input.setAttribute('aria-activedescendant', node.id);
      node.scrollIntoView({ block: 'nearest' });
    } else input.removeAttribute('aria-activedescendant');
  };
  const filter = () => {
    const query = normalizeSearch(input.value);
    visible = entries.filter(entry => {
      entry.node.hidden = entry.option.value !== '' && !entry.search.includes(query);
      entry.node.setAttribute('aria-selected', String(entry.option.value === select.value));
      return !entry.node.hidden;
    });
    highlight(-1);
    status.textContent = visible.some(entry => entry.option.value !== '') ? '' : 'Nenhuma loja encontrada.';
  };
  const open = () => {
    if (!popup.hidden) return;
    popup.hidden = false;
    input.setAttribute('aria-expanded', 'true');
    input.value = '';
    filter();
    highlight(visible.findIndex(entry => entry.option.value === select.value));
  };
  input.addEventListener('focus', open);
  input.addEventListener('click', open);
  input.addEventListener('input', () => {
    popup.hidden = false;
    input.setAttribute('aria-expanded', 'true');
    filter();
  });
  input.addEventListener('keydown', event => {
    if (event.isComposing) return;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      open();
      const step = event.key === 'ArrowDown' ? 1 : -1;
      highlight(active < 0 ? (step === 1 ? 0 : visible.length - 1) : (active + step + visible.length) % visible.length);
    } else if (event.key === 'Enter') {
      event.preventDefault();
      if (!popup.hidden && visible[active]) choose(visible[active].option);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      close();
    } else if (event.key === 'Tab') close();
  });
  input.addEventListener('blur', close);
  document.addEventListener('click', event => { if (!control.contains(event.target)) close(); });
  select.addEventListener('change', close);
  root.addEventListener('submit', close);
  popup.append(list, status);
  control.append(input, popup);
  select.before(control);
  label.htmlFor = input.id;
  select.hidden = true;
  root.dataset.bound = 'true';
  close();
}
