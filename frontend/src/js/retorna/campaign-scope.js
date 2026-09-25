export function bindCampaignScope() {
  const application = document.querySelector('[data-campaign-application]');
  const section = document.querySelector('[data-campaign-stores]');
  if (!application || !section) return;
  const inputs = section.querySelectorAll('input[name="lojas"]');
  const update = (preserveErrors = false) => {
    const specific = application.value === 'LOJAS';
    section.hidden = !specific && !(preserveErrors && section.dataset.hasErrors === 'true');
    inputs.forEach(input => { input.disabled = !specific; });
  };
  application.addEventListener('change', () => update());
  update(true);
}
