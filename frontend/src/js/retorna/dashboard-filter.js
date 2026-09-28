export function bindDashboardFilter() {
  const form = document.querySelector('form.retorna-dashboard-filter[data-store-search]');
  if (!form || form.dataset.dashboardFilterBound) return;
  const select = form.querySelector('select[name="loja"]');
  const button = form.querySelector('button[type="submit"]');
  // Keep the manual fallback when the native submission API is unavailable.
  if (!select || !button || typeof form.requestSubmit !== 'function') return;
  form.dataset.dashboardFilterBound = 'true';
  const key = 'retorna.dashboard.scroll.v1:' + window.location.pathname;
  let previous = select.value;

  const restore = () => {
    try {
      const saved = window.sessionStorage.getItem(key);
      if (saved === null) return;
      const top = Number(saved);
      if (Number.isFinite(top) && top >= 0) {
        window.scrollTo({ top, left: 0, behavior: 'instant' });
      }
      window.sessionStorage.removeItem(key);
    } catch { /* Restricted storage must not interfere with filtering. */ }
  };
  // Wait for page layout (including charts) and native scroll restoration.
  const afterLayout = () => window.requestAnimationFrame(restore);
  if (document.readyState === 'complete') afterLayout();
  else window.addEventListener('pageshow', afterLayout, { once: true });

  select.addEventListener('change', () => {
    if (select.value === previous) return;
    previous = select.value;
    try {
      window.sessionStorage.setItem(key, String(window.scrollY));
    } catch { /* Filtering still works without remembering scroll. */ }
    form.requestSubmit();
  });
  button.hidden = true;
}
