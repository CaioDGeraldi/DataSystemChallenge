export function bindIntegracaoForm() {
  const escopo = document.getElementById('id_escopo');
  const lojas = document.getElementById('id_lojas');
  if (!escopo || !lojas || !document.getElementById('selecao-lojas')) return;
  function atualizarLojas(preservarErros = false) {
      const restrito = escopo.value === 'LOJAS';
      const secao = document.getElementById('selecao-lojas');
      secao.hidden = !restrito && !(preservarErros && secao.dataset.hasErrors === 'true');
      lojas.disabled = !restrito;
      lojas.required = restrito;
      if (!restrito) Array.from(lojas.options).forEach(option => { option.selected = false; });
  }
  escopo.addEventListener('change', () => atualizarLojas());
  atualizarLojas(true);

}
