import re

from django.core.exceptions import ValidationError


def normalizar_cpf(cpf):
    if not isinstance(cpf, str):
        raise ValidationError("CPF inválido.", code="cpf_invalido")

    sem_espacos = "".join(caractere for caractere in cpf if not caractere.isspace())
    if not re.fullmatch(r"(?:[0-9]{11}|[0-9]{3}\.[0-9]{3}\.[0-9]{3}-[0-9]{2})", sem_espacos):
        raise ValidationError("CPF inválido.", code="cpf_invalido")

    return sem_espacos.replace(".", "").replace("-", "")


def validar_cpf(cpf):
    cpf = normalizar_cpf(cpf)
    if len(set(cpf)) == 1:
        raise ValidationError("CPF inválido.", code="cpf_invalido")

    for tamanho in (9, 10):
        soma = sum(int(digito) * (tamanho + 1 - indice) for indice, digito in enumerate(cpf[:tamanho]))
        verificador = (soma * 10) % 11
        if verificador == 10:
            verificador = 0
        if verificador != int(cpf[tamanho]):
            raise ValidationError("CPF inválido.", code="cpf_invalido")
