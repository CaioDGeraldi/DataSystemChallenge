// Somente apresentação da conversão linear. Elegibilidade é calculada no domínio.
export function decimalInteiro(texto, casas) {
  const partes = String(texto).trim().replace(',', '.').match(/^(\d+)(?:\.(\d+))?$/);
  if (!partes || (partes[2] || '').length > casas) return null;
  return BigInt(partes[1]) * 10n ** BigInt(casas) + BigInt((partes[2] || '').padEnd(casas, '0') || '0');
}

export function moeda(centavos) {
  return `R$ ${(centavos / 100n).toLocaleString('pt-BR')},${String(centavos % 100n).padStart(2, '0')}`;
}

export function linhasConversao(minimo, incremento, taxa, pagina) {
  return Array.from({ length: 10 }, (_, indice) => {
    const pontos = minimo + (pagina * 10n + BigInt(indice)) * incremento;
    return { pontos, desconto: pontos * taxa };
  });
}

export function bindConversaoResgate(root = document) {
  root.querySelectorAll('[data-conversao-resgate]').forEach((bloco) => {
    const form = bloco.closest('form');
    const el = (nome) => bloco.querySelector(`[data-resgate-${nome}]`);
    const modal = el('modal');
    const campos = ['resgate_minimo_pontos', 'incremento_resgate_pontos', 'valor_monetario_por_ponto', 'limite_resgate_percentual'];
    let pagina = 0n;
    const atualizar = () => {
      const [minimo, incremento, taxa, limite] = campos.map((nome, i) => decimalInteiro(form.elements[nome].value, [0, 0, 2, 4][i]));
      const valido = minimo > 0n && incremento > 0n && taxa > 0n && limite !== null && limite <= 1000000n;
      el('linhas').replaceChildren();
      el('anterior').disabled = !valido || pagina === 0n;
      el('proxima').disabled = !valido;
      el('pagina').textContent = valido ? `Página ${pagina + 1n}` : 'Preencha valores válidos para visualizar a conversão.';
      el('preview').textContent = valido ? `${minimo.toLocaleString('pt-BR')} pontos = ${moeda(minimo * taxa)} de desconto` : 'Preencha mínimo, incremento, valor por ponto e limite para ver a prévia.';
      // R$ 100,00 × percentual / 100, truncado em centavos.
      el('limite').textContent = valido ? `Em uma compra de R$ 100,00, o limite é ${moeda(limite / 100n)} de desconto por Resgate.` : '';
      if (!valido) return;
      linhasConversao(minimo, incremento, taxa, pagina).forEach(({ pontos, desconto }) => {
        const linha = root.createElement('tr');
        [pontos.toLocaleString('pt-BR'), moeda(desconto)].forEach((texto) => {
          const celula = root.createElement('td');
          celula.textContent = texto;
          linha.append(celula);
        });
        el('linhas').append(linha);
      });
    };
    campos.forEach((nome) => form.elements[nome].addEventListener('input', () => { pagina = 0n; atualizar(); }));
    el('abrir').addEventListener('click', () => { atualizar(); modal.showModal(); });
    el('fechar').addEventListener('click', () => modal.close());
    el('anterior').addEventListener('click', () => { if (pagina > 0n) pagina--; atualizar(); });
    el('proxima').addEventListener('click', () => { pagina++; atualizar(); });
    atualizar();
  });
}
