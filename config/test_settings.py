import os
from pathlib import Path
import runpy
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.test import Client, SimpleTestCase
from django.urls import path


def formulario(request):
    return HttpResponse(get_token(request))


urlpatterns = [path("form/", formulario)]


class SettingsTests(SimpleTestCase):
    def carregar(self, *, local=True, **env):
        ambiente = {"DJANGO_SECRET_KEY": "somente-teste-de-settings"}
        if local:
            ambiente.update(
                POSTGRES_DB="banco_local",
                POSTGRES_USER="usuario_local",
                POSTGRES_PASSWORD="senha-ficticia",
                POSTGRES_HOST="127.0.0.1",
                POSTGRES_PORT="5434",
            )
        ambiente.update(env)
        with patch.dict(os.environ, ambiente, clear=True):
            return runpy.run_path(str(Path(__file__).with_name("settings.py")))

    def test_postgres_local_sem_url_ou_com_url_vazia(self):
        for env in ({}, {"DATABASE_URL": ""}):
            with self.subTest(env=env):
                config = self.carregar(**env)
                self.assertEqual(config["DATABASES"], {"default": {
                    "ENGINE": "django.db.backends.postgresql",
                    "NAME": "banco_local", "USER": "usuario_local",
                    "PASSWORD": "senha-ficticia", "HOST": "127.0.0.1", "PORT": "5434",
                }})

    def test_url_tem_precedencia_e_dispensa_postgres_local(self):
        for local in (True, False):
            with self.subTest(local=local):
                config = self.carregar(local=local, DATABASE_URL=(
                    "postgres://remoto:senha-ficticia@db.example.test:5432/demo?sslmode=disable"
                ))
                self.assertEqual(list(config["DATABASES"]), ["default"])
                db = config["DATABASES"]["default"]
                self.assertEqual(db["ENGINE"], "django.db.backends.postgresql")
                self.assertEqual((db["NAME"], db["USER"], db["HOST"], db["PORT"]),
                                 ("demo", "remoto", "db.example.test", 5432))
                self.assertEqual(db["OPTIONS"]["sslmode"], "require")

    def test_url_nao_aceita_sqlite(self):
        with self.assertRaises(ImproperlyConfigured):
            self.carregar(DATABASE_URL="sqlite:///:memory:")

    def test_hosts_e_origens_multiplos_ignoram_espacos_e_itens_vazios(self):
        config = self.carregar(
            DJANGO_ALLOWED_HOSTS=" demo.example.test, , segundo.example.test, ",
            DJANGO_CSRF_TRUSTED_ORIGINS=" https://demo.example.test, ,https://segundo.example.test,",
        )
        self.assertEqual(config["ALLOWED_HOSTS"], ["demo.example.test", "segundo.example.test"])
        self.assertEqual(config["CSRF_TRUSTED_ORIGINS"],
                         ["https://demo.example.test", "https://segundo.example.test"])

    def test_defaults_locais_e_producao(self):
        for debug in ("true", "false"):
            with self.subTest(debug=debug):
                config = self.carregar(DJANGO_DEBUG=debug)
                producao = debug == "false"
                for name in ("SECURE_SSL_REDIRECT", "SESSION_COOKIE_SECURE", "CSRF_COOKIE_SECURE"):
                    self.assertEqual(config[name], producao)
                self.assertEqual(config["ALLOWED_HOSTS"],
                                 [] if producao else ["localhost", "127.0.0.1", "[::1]"])
                self.assertEqual(config["CSRF_TRUSTED_ORIGINS"], [])

    def test_redirect_configuravel_nao_desabilita_cookies_seguros(self):
        for valor, esperado in (("true", True), ("1", True), (" yes ", True), ("false", False), ("0", False)):
            with self.subTest(valor=valor):
                config = self.carregar(DJANGO_DEBUG="false", DJANGO_SECURE_SSL_REDIRECT=valor)
                self.assertEqual(config["SECURE_SSL_REDIRECT"], esperado)
                self.assertTrue(config["SESSION_COOKIE_SECURE"])
                self.assertTrue(config["CSRF_COOKIE_SECURE"])

    def cliente(self, config):
        # Exercita HTTP sem substituir conexões ou recarregar os settings globais.
        names = (
            "DEBUG", "ALLOWED_HOSTS", "CSRF_TRUSTED_ORIGINS", "SECURE_PROXY_SSL_HEADER",
            "SECURE_SSL_REDIRECT", "SESSION_COOKIE_SECURE", "CSRF_COOKIE_SECURE",
            "MIDDLEWARE",
        )
        self.enterContext(self.settings(**{
            **{name: config[name] for name in names},
            "ROOT_URLCONF": __name__,
        }))
        return Client(enforce_csrf_checks=True)

    def test_http_local_sem_redirect_e_csrf_funciona(self):
        client = self.cliente(self.carregar(DJANGO_DEBUG="true"))
        response = client.get("/form/", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.cookies["csrftoken"]["secure"])
        self.assertEqual(client.post("/form/", {"csrfmiddlewaretoken": response.content.decode()},
                                     HTTP_HOST="localhost").status_code, 200)

    def test_proxy_https_sem_loop_com_csrf_e_cookie_seguro(self):
        client = self.cliente(self.carregar(
            DJANGO_DEBUG="false", DJANGO_ALLOWED_HOSTS="demo.example.test",
            DJANGO_CSRF_TRUSTED_ORIGINS="https://origem.example.test",
        ))
        headers = {"HTTP_HOST": "demo.example.test"}
        redirect = client.get("/form/", **headers)
        self.assertEqual(redirect.status_code, 301)
        self.assertEqual(redirect["Location"], "https://demo.example.test/form/")
        headers["HTTP_X_FORWARDED_PROTO"] = "https"
        response = client.get("/form/", **headers)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.cookies["csrftoken"]["secure"])
        dados = {"csrfmiddlewaretoken": response.content.decode()}
        for origin in ("https://demo.example.test", "https://origem.example.test"):
            with self.subTest(origin=origin):
                self.assertEqual(client.post("/form/", dados, HTTP_ORIGIN=origin, **headers).status_code, 200)
        self.assertEqual(client.post("/form/", dados, HTTP_ORIGIN="https://intruso.example.test",
                                     **headers).status_code, 403)
        self.assertEqual(client.post("/form/", HTTP_ORIGIN="https://demo.example.test",
                                     **headers).status_code, 403)
