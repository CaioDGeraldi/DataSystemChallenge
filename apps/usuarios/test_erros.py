from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.test import Client, RequestFactory, SimpleTestCase, override_settings
from django.views import defaults

from config.views import csrf_failure


class PaginasErroTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.request = self.factory.get("/rota-de-teste/")

    def assert_pagina(self, response, status, texto):
        self.assertEqual(response.status_code, status)
        self.assertContains(response, texto, status_code=status)
        self.assertContains(response, "Retorna", status_code=status)

    def test_400_personalizado_nao_expoe_excecao(self):
        response = defaults.bad_request(
            self.request,
            Exception("segredo-interno"),
        )

        self.assert_pagina(response, 400, "Requisição inválida")
        self.assertNotContains(response, "segredo-interno", status_code=400)

    def test_403_personalizado_nao_expoe_excecao(self):
        response = defaults.permission_denied(
            self.request,
            PermissionDenied("segredo-interno"),
        )

        self.assert_pagina(response, 403, "Acesso não autorizado")
        self.assertNotContains(response, "segredo-interno", status_code=403)

    def test_404_personalizado_nao_expoe_excecao(self):
        response = defaults.page_not_found(
            self.request,
            Http404("segredo-interno"),
        )

        self.assert_pagina(response, 404, "Página não encontrada")
        self.assertNotContains(response, "segredo-interno", status_code=404)

    def test_500_personalizado_renderiza_sem_contexto_da_aplicacao(self):
        response = defaults.server_error(self.request)

        self.assert_pagina(
            response,
            500,
            "Não foi possível concluir esta operação",
        )

    def test_csrf_failure_nao_expoe_reason(self):
        response = csrf_failure(
            self.factory.post("/login/"),
            reason="segredo-csrf",
        )

        self.assert_pagina(
            response,
            403,
            "Não foi possível validar o formulário",
        )
        self.assertNotContains(response, "segredo-csrf", status_code=403)

    def test_csrf_real_usa_pagina_personalizada(self):
        client = Client(enforce_csrf_checks=True)

        response = client.post(
            "/login/",
            {"cpf": "52998224725", "senha": "qualquer"},
        )

        self.assert_pagina(
            response,
            403,
            "Não foi possível validar o formulário",
        )

    @override_settings(DEBUG=False)
    def test_404_real_usa_pagina_personalizada(self):
        response = self.client.get("/pagina-que-nao-existe/")

        self.assert_pagina(response, 404, "Página não encontrada")

    def test_404_da_api_continua_json(self):
        response = self.client.get("/api/rota-que-nao-existe/")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.headers["Content-Type"].split(";")[0],
            "application/json",
        )
        self.assertEqual(
            response.json()["erro"]["codigo"],
            "nao_encontrado",
        )
