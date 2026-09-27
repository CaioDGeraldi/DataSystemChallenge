import json
import os

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError

from apps.fidelidade.seed_fatecalcados import executar_seed, interpretar_data


class Command(BaseCommand):
    help = 'Cria uma única vez o cenário fictício FATECalçados, sem reset ou alteração de outros tenants.'

    def add_arguments(self, parser):
        parser.add_argument('--data-base', required=True, help='YYYY-MM-DD; referência às 12h em America/Sao_Paulo.')

    def handle(self, *args, **options):
        data_base = interpretar_data(options['data_base'])
        try:
            resumo = executar_seed(data_base, senha=os.environ.get('RETORNA_SEED_SENHA', ''),
                credencial_arquivo=os.environ.get('RETORNA_SEED_CREDENCIAL_ARQUIVO'))
        except (ValidationError, IntegrityError) as exc:
            # Não expor SQL, valores de identidades ou segredos em erros de corrida.
            raise CommandError('Carga recusada por validação/integridade; nenhuma carga parcial foi mantida.') from exc
        self.stdout.write(json.dumps(resumo, ensure_ascii=False, indent=2))
