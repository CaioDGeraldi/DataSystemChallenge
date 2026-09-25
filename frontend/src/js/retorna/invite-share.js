export function bindInviteShare() {
  const root = document.querySelector('[data-invite-share]');
  if (!root) return;
  const url = root.querySelector('[data-invite-url]').getAttribute('href');
  const copy = root.querySelector('[data-invite-copy]');
  const share = root.querySelector('[data-invite-native-share]');
  const feedback = root.querySelector('[data-invite-feedback]');
  copy.hidden = false;
  copy.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(url);
      feedback.textContent = 'Link copiado';
    } catch {
      feedback.textContent = 'Não foi possível copiar automaticamente. Selecione e copie o link acima.';
    }
  });
  if (typeof navigator.share === 'function') {
    share.hidden = false;
    share.addEventListener('click', async () => {
      try {
        await navigator.share({
          title: 'Convite Retorna',
          text: `Você recebeu um convite para acessar a empresa ${root.dataset.companyName} no Retorna.`,
          url,
        });
      } catch (error) {
        if (error.name !== 'AbortError') feedback.textContent = 'Não foi possível compartilhar. Use Copiar link ou selecione o link acima.';
      }
    });
  }
}
