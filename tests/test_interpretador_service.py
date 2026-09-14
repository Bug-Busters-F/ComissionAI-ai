"""
Testes unitários para o serviço orquestrador de interpretação de regras (Task S1-A04).
"""

from datetime import date
from decimal import Decimal
import unittest
from unittest.mock import MagicMock

from app.core.exceptions import LLMResponseParsingError
from app.core.services.interpretador import InterpretadorRegraService
from app.providers.base import LLMProvider
from app.schemas.regra import InterpretacaoRegraRequest


class TestInterpretadorRegraService(unittest.TestCase):
    def test_interpretador_cenario_sucesso_completo(self):
        mock_provider = MagicMock(spec=LLMProvider)
        mock_provider.complete.return_value = {
            "canal": "ECOMMERCE",
            "taxa_raw": "5%",
            "vigencia_inicio_raw": "dezembro",
            "vigencia_fim_raw": "dezembro",
            "criterios_nao_suportados": [],
            "ambiguidades_ou_duvidas": [],
        }

        service = InterpretadorRegraService(provider=mock_provider)
        request = InterpretacaoRegraRequest(
            texto="Pagar 5% no canal ecommerce durante dezembro",
            contexto={"ano_referencia": 2026},
        )

        response = service.interpretar(request)

        self.assertEqual(response.canal, "ECOMMERCE")
        self.assertEqual(response.taxa, Decimal("0.0500"))
        self.assertEqual(response.dataInicio, date(2026, 12, 1))
        self.assertEqual(response.dataFim, date(2026, 12, 31))
        self.assertEqual(response.confianca, Decimal("1.00"))
        self.assertEqual(response.pendencias, [])
        mock_provider.complete.assert_called_once()

    def test_interpretador_cenario_com_criterios_nao_suportados(self):
        mock_provider = MagicMock(spec=LLMProvider)
        mock_provider.complete.return_value = {
            "canal": None,
            "taxa_raw": "3%",
            "vigencia_inicio_raw": "dezembro",
            "vigencia_fim_raw": "dezembro",
            "criterios_nao_suportados": ["loja 75", "vendedores"],
            "ambiguidades_ou_duvidas": ["Canal de venda não identificado"],
        }

        service = InterpretadorRegraService(provider=mock_provider)
        request = InterpretacaoRegraRequest(
            texto="3% para os vendedores da loja 75 em dezembro",
            contexto={"ano_referencia": 2026},
        )

        response = service.interpretar(request)

        self.assertIsNone(response.canal)
        self.assertEqual(response.taxa, Decimal("0.0300"))
        self.assertEqual(response.dataInicio, date(2026, 12, 1))
        self.assertEqual(response.dataFim, date(2026, 12, 31))
        self.assertLess(response.confianca, Decimal("0.80"))
        self.assertTrue(any("não suportado" in p for p in response.pendencias))
        self.assertTrue(any("Canal" in p for p in response.pendencias))

    def test_interpretador_com_canal_padrao_no_contexto(self):
        mock_provider = MagicMock(spec=LLMProvider)
        mock_provider.complete.return_value = {
            "canal": None,
            "taxa_raw": "4%",
            "vigencia_inicio_raw": "a partir de outubro",
            "vigencia_fim_raw": None,
            "criterios_nao_suportados": [],
            "ambiguidades_ou_duvidas": [],
        }

        service = InterpretadorRegraService(provider=mock_provider)
        request = InterpretacaoRegraRequest(
            texto="Comissão de 4% a partir de outubro",
            contexto={"ano_referencia": 2026, "canal_padrao": "ECOMMERCE"},
        )

        response = service.interpretar(request)

        self.assertEqual(response.canal, "ECOMMERCE")
        self.assertEqual(response.taxa, Decimal("0.0400"))
        self.assertEqual(response.dataInicio, date(2026, 10, 1))
        self.assertIsNone(response.dataFim)
        self.assertEqual(response.confianca, Decimal("1.00"))
        self.assertEqual(response.pendencias, [])

    def test_interpretador_retorno_invalido_do_llm(self):
        mock_provider = MagicMock(spec=LLMProvider)
        # Retorna tipos incompatíveis que falham na validação do Pydantic
        mock_provider.complete.return_value = {
            "criterios_nao_suportados": "deveria ser lista e nao string",
        }

        service = InterpretadorRegraService(provider=mock_provider)
        request = InterpretacaoRegraRequest(
            texto="Comissão qualquer",
            contexto={},
        )

        with self.assertRaises(LLMResponseParsingError):
            service.interpretar(request)


if __name__ == "__main__":
    unittest.main()
