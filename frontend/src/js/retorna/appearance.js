export const STORAGE_KEY = 'retorna.interface.v1';
export function normalizeAppearance(value = {}) {
  const state = value && typeof value === 'object' ? value : {};
  return {
    theme: ['system', 'light', 'dark'].includes(state.theme) ? state.theme : 'system',
    fontScale: [100, 110, 120].includes(state.fontScale) ? state.fontScale : 100,
    formMode: ['steps', 'all'].includes(state.formMode) ? state.formMode : 'steps',
  };
}
export function effectiveTheme(theme, dark) {
  return theme === 'dark' || (theme === 'system' && dark) ? 'dark' : 'light';
}
export function readAppearance(storage) {
  try { return normalizeAppearance(JSON.parse(storage.getItem(STORAGE_KEY))); }
  catch { return normalizeAppearance(); }
}
export function writeAppearance(storage, state) {
  try { storage.setItem(STORAGE_KEY, JSON.stringify(normalizeAppearance(state))); return true; }
  catch { return false; }
}
export function initialFormMode(explicit, preference) {
  return ['steps', 'all'].includes(explicit) ? explicit : preference === 'all' ? 'all' : 'steps';
}
export function bindAppearance() {
  const root = document.documentElement;
  if (root.dataset.retornaAppearanceBound) return;
  root.dataset.retornaAppearanceBound = "true";
  let storage;
  try { storage = window.localStorage; } catch { /* Private/restricted browser. */ }
  let state = readAppearance(storage);
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  const panel = document.querySelector('[data-appearance-panel]');
  const apply = () => {
    root.dataset.retornaTheme = effectiveTheme(state.theme, media.matches);
    root.dataset.retornaFontScale = String(state.fontScale);
    root.dataset.retornaFormMode = state.formMode;
    panel?.querySelectorAll('input[type="radio"]').forEach(input => {
      input.checked = String(state[input.name]) === input.value;
    });
  };
  apply();
  media.addEventListener('change', apply);
  if (!panel || typeof panel.showModal !== 'function') return;
  let opener;
  document.querySelectorAll('[data-appearance-open]').forEach(button => {
    button.hidden = false;
    button.addEventListener('click', () => {
      const menu = button.closest('[data-user-menu]');
      opener = menu ? document.querySelector('[data-user-menu-trigger]') : button;
      if (menu) {
        menu.hidden = true;
        opener?.setAttribute('aria-expanded', 'false');
      }
      panel.showModal();
      panel.querySelector('input:checked')?.focus();
    });
  });
  panel.addEventListener('close', () => opener?.focus());
  panel.querySelector('[data-appearance-close]').addEventListener('click', () => panel.close());
  const save = () => {
    apply();
    const saved = writeAppearance(storage, state);
    panel.querySelector('[data-appearance-status]').textContent = saved
      ? 'Preferências salvas neste navegador.'
      : 'Preferências aplicadas nesta página. O navegador não permitiu salvar.';
  };
  panel.addEventListener('change', event => {
    const input = event.target;
    if (!input.matches('input[type="radio"]')) return;
    state = normalizeAppearance({ ...state, [input.name]: input.name === 'fontScale' ? Number(input.value) : input.value });
    save();
  });
  panel.querySelector('[data-appearance-reset]').addEventListener('click', () => { state = normalizeAppearance(); save(); });
}
