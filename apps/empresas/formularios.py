"""Agrupamento exclusivamente visual de campos existentes."""


class FormularioCompostoMixin:
    grupos_formulario = ()

    @property
    def etapas_formulario(self):
        etapas = []
        for rotulo, nomes in self.grupos_formulario:
            campos = [self[nome] for nome in nomes if nome in self.fields and not self[nome].is_hidden]
            if campos:
                etapas.append({'rotulo': rotulo, 'campos': campos,
                               'tem_erros': any(campo.errors for campo in campos)})
        return etapas if len(etapas) >= 2 else []
