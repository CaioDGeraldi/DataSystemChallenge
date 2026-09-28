// Both native disclosures and the Management button/panel share this contract.
export function closeUserMenu(menu, { restoreFocus = false } = {}) {
  const root = menu.closest('.retorna-user-menu');
  const trigger = root?.querySelector('[data-user-menu-trigger]');
  if (root?.tagName === 'DETAILS') root.open = false;
  else menu.hidden = true;
  trigger?.setAttribute('aria-expanded', 'false');
  if (restoreFocus) trigger?.focus();
}

export function bindUserMenu() {
  if (document.documentElement.dataset.retornaUserMenuEnhanced) return;
  const menus = Array.from(document.querySelectorAll('.retorna-user-menu')).flatMap(root => {
    const trigger = root.querySelector('[data-user-menu-trigger]');
    const menu = root.querySelector('[data-user-menu]');
    if (!trigger || !menu || trigger.getAttribute('aria-controls') !== menu.id) return [];
    const native = root.tagName === 'DETAILS';
    return [{ root, trigger, menu, isOpen: () => native ? root.open : !menu.hidden,
      setOpen: () => { if (native) root.open = true; else menu.hidden = false; } }];
  });
  if (!menus.length) return;
  document.documentElement.dataset.retornaUserMenuEnhanced = 'true';

  const closeOthers = current => menus.forEach(item => {
    if (item !== current && item.isOpen()) closeUserMenu(item.menu);
  });
  for (const item of menus) {
    const { root, trigger, menu } = item;
    closeUserMenu(menu);
    trigger.addEventListener('click', event => {
      event.preventDefault(); // Summary is toggled here; without JS it remains native.
      if (item.isOpen()) {
        closeUserMenu(menu);
      } else {
        closeOthers(item);
        item.setOpen();
        trigger.setAttribute('aria-expanded', 'true');
        menu.querySelector('a[href], button:not([hidden]):not(:disabled), input:not([type="hidden"]):not(:disabled), select:not(:disabled)')?.focus();
      }
    });
    if (root.tagName === 'DETAILS') root.addEventListener('toggle', () => {
      if (item.isOpen()) closeOthers(item);
      trigger.setAttribute('aria-expanded', String(item.isOpen()));
    });
  }
  document.addEventListener('click', event => {
    menus.forEach(item => {
      if (item.isOpen() && !item.root.contains(event.target)) closeUserMenu(item.menu);
    });
  });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    menus.forEach(item => {
      if (item.isOpen()) {
        event.preventDefault();
        closeUserMenu(item.menu, { restoreFocus: true });
      }
    });
  });
}
