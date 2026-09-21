"""
Testes unitários para o serviço orquestrador de interpretação de regras (Task S1-A04).
"""

from datetime import date
from decimal import Decimal
import unittest
from unittest.mock import MagicMock, patch

from app.core.exceptions import LLMProviderError, LLMResponseParsingError, LLMTimeoutError
from app.core.services.interpretador import InterpretadorRegraService
from app.providers.base import LLMProvider
from app.schemas.regra import InterpretacaoRegraRequest


CONTEXTO_COM_CATALOGO = {
    "ano_referencia": 2026,
    "dicionario_dimensoes": {
        "marcas": {"10": "PRETO", "20": "BRANCO", "30": "AZUL"},
        "cargos": {
            "100": "VENDEDOR LOJA",
            "150": "GERENTE DE LOJA",
            "200": "VENDEDOR BALCAO",
        },
        "canais": ["LOJA_FISICA", "ECOMMERCE", "BALCAO", "WHATSAPP"],
    },
}


class TestInterpretadorRegraService(unittest.TestCase):

    def test_interpretador_cenario_sucesso_ecommerce(self):
        """Cenário B: apenas canal e taxa, sem dimensões de marca/cargo/loja."""
        mock_provider = MagicMock(spec=LLMProvider)
        mock_provider.complete.return_value = {
            "canal": "ECOMMERCE",
            "taxa_raw": "5%",
            "vigencia_inicio_raw": "dezembro",
            "vigencia_fim_raw": "dezembro",
            "criterios_nao_suportados": [],
            "ambiguidades_ou_duvidas": [],
            "marca_raw": None,
            "loja_raw": None,
            "cargo_raw": None,
        }

        service = InterpretadorRegraService(provider=mock_provider)
        request = InterpretacaoRegraRequest(
            texto="Pagar 5% no canal ecommerce durante dezembro",
            contexto={"ano_referencia": 2026},
        )

        response = service.interpretar(request)

        self.assertEqual(response.canal, "ECOMMERCE")
        self.assertIsNone(response.codMarca)
        self.assertIsNone(response.descrMarca)
        self.assertIsNone(response.codCargo)
        self.assertIsNone(response.descriCargo)
        self.assertIsNone(response.codLoja)
        self.assertEqual(response.taxa, Decimal("0.0500"))
        self.assertEqual(response.dataInicio, date(2026, 12, 1))
        self.assertEqual(response.dataFim, date(2026, 12, 31))
        self.assertEqual(response.pendencias, [])
        mock_provider.complete.assert_called_once()

    def test_interpretador_cenario_a_com_marca_cargo_loja(self):
        """Cenário A: regra completa com marca PRETO, cargo VENDEDOR LOJA, loja 75."""
        mock_provider = MagicMock(spec=LLMProvider)
        mock_provider.complete.return_value = {
            "canal": "LOJA_FISICA",
            "taxa_raw": "3.5%",
            "vigencia_inicio_raw": "outubro de 2026",
            "vigencia_fim_raw": "outubro de 2026",
            "criterios_nao_suportados": [],
            "ambiguidades_ou_duvidas": [],
            "marca_raw": "PRETO",
            "loja_raw": "75",
            "cargo_raw": "VENDEDOR LOJA",
        }

        service = InterpretadorRegraService(provider=mock_provider)
        request = InterpretacaoRegraRequest(
            texto="Comissão de 3.5% para os vendedores da marca PRETO na loja 75 durante todo o mês de outubro de 2026",
            contexto=CONTEXTO_COM_CATALOGO,
        )

        response = service.interpretar(request)

        self.assertEqual(response.canal, "LOJA_FISICA")
        self.assertEqual(response.codMarca, 10)
        self.assertEqual(response.descrMarca, "PRETO")
        self.assertEqual(response.codCargo, 100)
        self.assertEqual(response.descriCargo, "VENDEDOR LOJA")
        self.assertEqual(response.codLoja, 75)
        self.assertEqual(response.taxa, Decimal("0.0350"))
        self.assertEqual(response.dataInicio, date(2026, 10, 1))
        self.assertEqual(response.dataFim, date(2026, 10, 31))
        self.assertEqual(response.pendencias, [])

    def test_interpretador_cargo_ambiguo_retorna_null_e_pendencia(self):
        """Cenário C parcial: cargo 'gerentes' ambíguo — não existe entrada única no catálogo."""
        mock_provider = MagicMock(spec=LLMProvider)
        mock_provider.complete.return_value = {
            "canal": None,
            "taxa_raw": None,
            "vigencia_inicio_raw": None,
            "vigencia_fim_raw": None,
            "criterios_nao_suportados": [],
            "ambiguidades_ou_duvidas": [
                "Ambiguidade de cargo: 'gerentes' pode referir-se a múltiplas funções no catálogo"
            ],
            "marca_raw": None,
            "loja_raw": None,
            "cargo_raw": "gerentes",  # não existe entrada exata no catálogo
        }

        contexto_com_dois_gerentes = {
            "ano_referencia": 2026,
            "dicionario_dimensoes": {
                "marcas": {"10": "PRETO"},
                "cargos": {
                    "150": "GERENTE DE LOJA",
                    "151": "GERENTE QUIOSQUE",
                },
                "canais": ["LOJA_FISICA", "ECOMMERCE"],
            },
        }

        service = InterpretadorRegraService(provider=mock_provider)
        request = InterpretacaoRegraRequest(
            texto="Pagar comissão especial para os gerentes",
            contexto=contexto_com_dois_gerentes,
        )

        response = service.interpretar(request)

        self.assertIsNone(response.codCargo)
        self.assertIsNone(response.descriCargo)
        self.assertTrue(len(response.pendencias) > 0)

    def test_interpretador_cenario_c_completo(self):
        """Cenário C: 'Pagar comissão especial para os gerentes' com cargos compartilhando código 150."""
        mock_provider = MagicMock(spec=LLMProvider)
        mock_provider.complete.return_value = {
            "canal": None,
            "taxa_raw": None,
            "vigencia_inicio_raw": None,
            "vigencia_fim_raw": None,
            "criterios_nao_suportados": [],
            "ambiguidades_ou_duvidas": [
                "Percentual de comissão não identificado.",
                "Data de início da vigência não identificada.",
            ],
            "marca_raw": None,
            "loja_raw": None,
            "cargo_raw": "gerentes",
        }

        contexto_cenario_c = {
            "ano_referencia": 2026,
            "dicionario_dimensoes": {
                "cargos": [
                    {"codCargo": 150, "descriCargo": "GERENTE DE LOJA"},
                    {"codCargo": 150, "descriCargo": "GERENTE QUIOSQUE"},
                ],
                "canais": ["LOJA_FISICA", "ECOMMERCE"],
            },
        }

        service = InterpretadorRegraService(provider=mock_provider)
        request = InterpretacaoRegraRequest(
            texto="Pagar comissão especial para os gerentes",
            contexto=contexto_cenario_c,
        )

        response = service.interpretar(request)

        self.assertIsNone(response.canal)
        self.assertIsNone(response.codMarca)
        self.assertEqual(response.codCargo, 150)
        self.assertIsNone(response.descriCargo)
        self.assertIsNone(response.codLoja)
        self.assertIsNone(response.taxa)
        self.assertIsNone(response.dataInicio)
        self.assertIsNone(response.dataFim)
        self.assertTrue(any("Ambiguidade de cargo" in p for p in response.pendencias))
        self.assertTrue(any("Percentual" in p for p in response.pendencias))
        self.assertTrue(any("vigência" in p for p in response.pendencias))

    def test_interpretador_marca_nao_encontrada_no_catalogo(self):
        """Marca mencionada no texto não existe no catálogo."""
        mock_provider = MagicMock(spec=LLMProvider)
        mock_provider.complete.return_value = {
            "canal": "ECOMMERCE",
            "taxa_raw": "4%",
            "vigencia_inicio_raw": "novembro de 2026",
            "vigencia_fim_raw": "novembro de 2026",
            "criterios_nao_suportados": [],
            "ambiguidades_ou_duvidas": [],
            "marca_raw": "VERDE",  # não existe no catálogo
            "loja_raw": None,
            "cargo_raw": None,
        }

        service = InterpretadorRegraService(provider=mock_provider)
        request = InterpretacaoRegraRequest(
            texto="4% no ecommerce para a marca VERDE em novembro",
            contexto=CONTEXTO_COM_CATALOGO,
        )

        response = service.interpretar(request)

        self.assertIsNone(response.codMarca)
        self.assertIsNone(response.descrMarca)
        self.assertTrue(any("VERDE" in p or "marca" in p.lower() for p in response.pendencias))

    def test_interpretador_dicionario_dimensoes_define_canais_permitidos(self):
        """Canais do dicionario_dimensoes têm prioridade sobre a lista interna."""
        mock_provider = MagicMock(spec=LLMProvider)
        mock_provider.complete.return_value = {
            "canal": "APP",  # canal disponível no catálogo enviado, mas não no padrão MVP
            "taxa_raw": "4%",
            "vigencia_inicio_raw": "a partir de outubro",
            "vigencia_fim_raw": None,
            "criterios_nao_suportados": [],
            "ambiguidades_ou_duvidas": [],
            "marca_raw": None,
            "loja_raw": None,
            "cargo_raw": None,
        }

        service = InterpretadorRegraService(provider=mock_provider)
        request = InterpretacaoRegraRequest(
            texto="Comissão de 4% via APP a partir de outubro",
            contexto={
                "ano_referencia": 2026,
                "dicionario_dimensoes": {
                    "marcas": {},
                    "cargos": {},
                    "canais": ["LOJA_FISICA", "ECOMMERCE", "APP"],
                },
            },
        )

        response = service.interpretar(request)

        self.assertEqual(response.canal, "APP")
        self.assertEqual(response.pendencias, [])

    def test_interpretador_com_canal_padrao_no_contexto(self):
        """Canal padrão legado no contexto ainda funciona quando LLM não extrai canal."""
        mock_provider = MagicMock(spec=LLMProvider)
        mock_provider.complete.return_value = {
            "canal": None,
            "taxa_raw": "4%",
            "vigencia_inicio_raw": "a partir de outubro",
            "vigencia_fim_raw": None,
            "criterios_nao_suportados": [],
            "ambiguidades_ou_duvidas": [],
            "marca_raw": None,
            "loja_raw": None,
            "cargo_raw": None,
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
        self.assertEqual(response.pendencias, [])

    def test_interpretador_retorno_invalido_do_llm(self):
        """Retorno com tipo incompatível deve levantar LLMResponseParsingError."""
        mock_provider = MagicMock(spec=LLMProvider)
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

    @patch("app.core.services.interpretador.time.sleep")
    def test_interpretador_retry_bem_sucedido_apos_falha_transitoria(self, mock_sleep):
        """1ª chamada falha com LLMProviderError (ex: alta demanda), 2ª tem sucesso."""
        mock_provider = MagicMock(spec=LLMProvider)
        mock_provider.complete.side_effect = [
            LLMProviderError("Alta demanda no provedor."),
            {
                "canal": "ECOMMERCE",
                "taxa_raw": "5%",
                "vigencia_inicio_raw": "dezembro",
                "vigencia_fim_raw": "dezembro",
                "criterios_nao_suportados": [],
                "ambiguidades_ou_duvidas": [],
                "marca_raw": None,
                "loja_raw": None,
                "cargo_raw": None,
            },
        ]

        service = InterpretadorRegraService(provider=mock_provider)
        request = InterpretacaoRegraRequest(texto="Pagar 5% no ecommerce em dezembro", contexto={})

        response = service.interpretar(request)

        self.assertEqual(response.canal, "ECOMMERCE")
        self.assertEqual(response.taxa, Decimal("0.0500"))
        self.assertEqual(mock_provider.complete.call_count, 2)
        mock_sleep.assert_called_once()

    @patch("app.core.services.interpretador.time.sleep")
    def test_interpretador_retry_falha_nas_duas_tentativas_propaga_erro(self, mock_sleep):
        """Se as duas tentativas falharem com LLMProviderError, o erro deve propagar."""
        mock_provider = MagicMock(spec=LLMProvider)
        mock_provider.complete.side_effect = LLMProviderError("Alta demanda no provedor.")

        service = InterpretadorRegraService(provider=mock_provider)
        request = InterpretacaoRegraRequest(texto="Pagar 5% no ecommerce em dezembro", contexto={})

        with self.assertRaises(LLMProviderError):
            service.interpretar(request)

        self.assertEqual(mock_provider.complete.call_count, 2)

    def test_interpretador_nao_retenta_timeout(self):
        """LLMTimeoutError não deve ser retentado (já consumiu o orçamento de tempo)."""
        mock_provider = MagicMock(spec=LLMProvider)
        mock_provider.complete.side_effect = LLMTimeoutError("Tempo limite excedido.")

        service = InterpretadorRegraService(provider=mock_provider)
        request = InterpretacaoRegraRequest(texto="Pagar 5% no ecommerce em dezembro", contexto={})

        with self.assertRaises(LLMTimeoutError):
            service.interpretar(request)

        self.assertEqual(mock_provider.complete.call_count, 1)


if __name__ == "__main__":
    unittest.main()
