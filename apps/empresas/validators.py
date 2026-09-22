import re

from django.core.exceptions import ValidationError


def normalizar_cnpj(cnpj):
    if not isinstance(cnpj, str):
        raise ValidationError("CNPJ inválido.", code="cnpj_invalido")

    sem_espacos = "".join(caractere for caractere in cnpj if not caractere.isspace())
    if not re.fullmatch(r"(?:[0-9]{14}|[0-9]{2}\.[0-9]{3}\.[0-9]{3}/[0-9]{4}-[0-9]{2})", sem_espacos):
        raise ValidationError("CNPJ inválido.", code="cnpj_invalido")

    return sem_espacos.replace(".", "").replace("/", "").replace("-", "")


def validar_cnpj(cnpj):
    cnpj = normalizar_cnpj(cnpj)
    if len(set(cnpj)) == 1:
        raise ValidationError("CNPJ inválido.", code="cnpj_invalido")

    for tamanho, pesos in (
        (12, (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)),
        (13, (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)),
    ):
        soma = sum(int(digito) * peso for digito, peso in zip(cnpj[:tamanho], pesos))
        resto = soma % 11
        verificador = 0 if resto < 2 else 11 - resto
        if verificador != int(cnpj[tamanho]):
            raise ValidationError("CNPJ inválido.", code="cnpj_invalido")
