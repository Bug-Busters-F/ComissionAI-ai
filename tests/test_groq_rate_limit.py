"""Tratamento de 429 e orçamento da Groq, sem rede ou espera real."""

import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import MagicMock, patch

import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from app.core.exceptions import LLMAuthenticationError, LLMRateLimitError, LLMTimeoutError
from app.providers.groq import GroqProvider, _retry_after_seconds


class TestGroqRateLimit(unittest.TestCase):
    def setUp(self):
        sdk = types.ModuleType('groq')
        for name in ['AuthenticationError', 'RateLimitError', 'PermissionDeniedError', 'APITimeoutError', 'APIConnectionError', 'NotFoundError', 'BadRequestError', 'InternalServerError', 'APIStatusError']:
            setattr(sdk, name, type(name, (Exception,), {}))
        sdk.Groq = MagicMock()
        self.sdk = sdk
        self.patches = [patch.dict(sys.modules, {'groq': sdk}),
                        patch('app.core.config.settings.llm_api_key', 'secret-for-test'),
                        patch('app.core.config.settings.llm_timeout_seconds', 30),
                        patch('app.core.config.settings.llm_rate_limit_max_retries', 1),
                        patch('app.core.config.settings.llm_rate_limit_max_wait_seconds', 5)]
        for p in self.patches:
            p.start(); self.addCleanup(p.stop)
        self.now = 0.0
        self.sleeps = []
        clock = patch('app.providers.groq.time.monotonic', lambda: self.now)
        clock.start(); self.addCleanup(clock.stop)
        sleep = patch('app.providers.groq.time.sleep', self.sleep)
        sleep.start(); self.addCleanup(sleep.stop)
        self.provider = GroqProvider()
        self.create = self.provider._client.chat.completions.create
        self.success = MagicMock()
        self.success.choices[0].message.content = '{"regras": []}'

    def sleep(self, seconds):
        self.sleeps.append(seconds); self.now += seconds

    def error(self, delay=None):
        e = self.sdk.RateLimitError('raw secret-for-test must not escape')
        headers = {} if delay is None else {'retry-after': str(delay)}
        e.response = httpx.Response(429, headers=headers)
        return e

    def test_retry_respeita_cabecalho_e_reduz_timeout_da_segunda_tentativa(self):
        self.create.side_effect = [self.error(2), self.success]
        self.assertEqual(self.provider.complete('texto', {}), {'regras': []})
        self.assertEqual(self.sleeps, [2])
        self.assertEqual(self.create.call_count, 2)
        self.assertEqual(self.create.call_args_list[0].kwargs['timeout'].read, 30)
        self.assertEqual(self.create.call_args_list[1].kwargs['timeout'].read, 28)

    def test_falha_persistente_termina_apos_uma_retentativa_e_mantem_retry_after(self):
        self.create.side_effect = self.error(1.2)
        with self.assertRaises(LLMRateLimitError) as caught:
            self.provider.complete('texto', {})
        self.assertEqual(self.create.call_count, 2)
        self.assertEqual(self.sleeps, [1.2])
        self.assertEqual(caught.exception.retry_after_seconds, 1.2)
        self.assertNotIn('secret-for-test', caught.exception.message)
        self.assertIn('2 segundo', caught.exception.message)

    def test_sem_cabecalho_nao_retenta_cegamente(self):
        self.create.side_effect = self.error()
        with self.assertRaises(LLMRateLimitError) as caught:
            self.provider.complete('texto', {})
        self.assertEqual(self.create.call_count, 1)
        self.assertEqual(self.sleeps, [])
        self.assertIsNone(caught.exception.retry_after_seconds)

    def test_espera_longa_ou_diaria_nao_bloqueia_o_servidor(self):
        for delay in [6, 60, 86400]:
            with self.subTest(delay=delay):
                self.create.reset_mock(); self.create.side_effect = self.error(delay)
                with self.assertRaises(LLMRateLimitError) as caught:
                    self.provider.complete('texto', {})
                self.assertEqual(self.create.call_count, 1)
                self.assertEqual(caught.exception.retry_after_seconds, delay)
        self.assertEqual(self.sleeps, [])

    def test_cabecalho_invalido_nao_produz_loop_ou_erro_inesperado(self):
        for delay in ['-1', 'nan', 'inf', 'muito tempo', '']:
            with self.subTest(delay=delay):
                self.create.reset_mock(); self.create.side_effect = self.error(delay)
                with self.assertRaises(LLMRateLimitError) as caught:
                    self.provider.complete('texto', {})
                self.assertEqual(self.create.call_count, 1)
                self.assertIsNone(caught.exception.retry_after_seconds)
        self.assertEqual(self.sleeps, [])

    def test_retry_pode_ser_desabilitado(self):
        self.create.side_effect = self.error(1)
        with patch('app.core.config.settings.llm_rate_limit_max_retries', 0):
            with self.assertRaises(LLMRateLimitError): self.provider.complete('texto', {})
        self.assertEqual(self.create.call_count, 1)
        self.assertEqual(self.sleeps, [])

    def test_nao_dorme_quando_retry_after_nao_cabe_no_orcamento_restante(self):
        def fail(**kwargs):
            self.now = 29.5
            raise self.error(1)
        self.create.side_effect = fail
        with self.assertRaises(LLMRateLimitError): self.provider.complete('texto', {})
        self.assertEqual(self.sleeps, [])
        self.assertEqual(self.create.call_count, 1)

    def test_erro_de_autenticacao_e_permissao_nao_retenta(self):
        for cls in [self.sdk.AuthenticationError, self.sdk.PermissionDeniedError]:
            with self.subTest(error=cls.__name__):
                self.create.reset_mock(); self.create.side_effect = cls('secret-for-test')
                with self.assertRaises(LLMAuthenticationError): self.provider.complete('texto', {})
                self.assertEqual(self.create.call_count, 1)
        self.assertEqual(self.sleeps, [])

    def test_fallback_ipv4_nao_reinicia_timeout_apos_espera(self):
        self.create.side_effect = [self.error(2), self.sdk.APIConnectionError('transport')]
        with patch.object(self.provider, '_complete_ipv4', return_value=self.success) as fallback:
            self.provider.complete('texto', {})
        self.assertEqual(fallback.call_args.args[0]['timeout'].read, 28)

    def test_timeout_esgotado_nao_faz_fallback_com_novo_orcamento(self):
        def expire(**kwargs):
            self.now = 30
            raise self.sdk.APITimeoutError('deadline')
        self.create.side_effect = expire
        with patch.object(self.provider, '_complete_ipv4') as fallback:
            with self.assertRaises(LLMTimeoutError): self.provider.complete('texto', {})
            fallback.assert_not_called()
        self.assertEqual(self.sleeps, [])

    def test_retry_after_data_http_e_aceito(self):
        now = datetime(2026, 10, 22, 20, 0, tzinfo=timezone.utc)
        date = format_datetime(now + timedelta(seconds=4), usegmt=True)
        with patch('app.providers.groq.datetime') as clock:
            clock.now.return_value = now
            self.assertEqual(_retry_after_seconds(self.error(date)), 4)


if __name__ == '__main__':
    unittest.main()
