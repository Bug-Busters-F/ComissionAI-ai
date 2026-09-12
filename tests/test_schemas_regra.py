"""
Testes unitários para os schemas Pydantic de regras (Task S1-A02).
"""

from datetime import date
from decimal import Decimal
import unittest
from pydantic import ValidationError

from src.app.schemas.regra import (
    InterpretacaoRegraRequest,
    InterpretacaoRegraResponse,
)


class TestInterpretacaoRegraRequest(unittest.TestCase):
    """Testes do payload de entrada InterpretacaoRegraRequest."""

    def test_request_valido_com_contexto(self):
        req = InterpretacaoRegraRequest(
            texto="Pagar 5% no canal ecommerce durante dezembro",
            contexto={"canal_padrao": "ECOMMERCE", "ano_referencia": 2026},
        )
        self.assertEqual(req.texto, "Pagar 5% no canal ecommerce durante dezembro")
        self.assertEqual(req.contexto["canal_padrao"], "ECOMMERCE")
        self.assertEqual(req.contexto["ano_referencia"], 2026)

    def test_request_sem_contexto_usa_default(self):
        req = InterpretacaoRegraRequest(texto="Pagar 3% no canal loja_fisica")
        self.assertEqual(req.texto, "Pagar 3% no canal loja_fisica")
        self.assertEqual(req.contexto, {})

    def test_request_sem_texto_lanca_validacao(self):
        with self.assertRaises(ValidationError):
            InterpretacaoRegraRequest()  # type: ignore


class TestInterpretacaoRegraResponse(unittest.TestCase):
    """Testes da proposta de regra estruturada InterpretacaoRegraResponse."""

    def test_response_valida_completa(self):
        resp = InterpretacaoRegraResponse(
            canal="ecommerce ",
            taxa=Decimal("0.0500"),
            dataInicio=date(2026, 12, 1),
            dataFim=date(2026, 12, 31),
            confianca=Decimal("0.95"),
            pendencias=[],
        )
        self.assertEqual(resp.canal, "ECOMMERCE")
        self.assertEqual(resp.taxa, Decimal("0.0500"))
        self.assertEqual(resp.dataInicio, date(2026, 12, 1))
        self.assertEqual(resp.dataFim, date(2026, 12, 31))
        self.assertEqual(resp.confianca, Decimal("0.95"))
        self.assertEqual(resp.pendencias, [])

    def test_response_valida_com_data_fim_null(self):
        resp = InterpretacaoRegraResponse(
            canal="LOJA_FISICA",
            taxa=Decimal("0.0300"),
            dataInicio=date(2026, 10, 1),
            dataFim=None,
            confianca=Decimal("0.90"),
        )
        self.assertEqual(resp.canal, "LOJA_FISICA")
        self.assertEqual(resp.taxa, Decimal("0.0300"))
        self.assertIsNone(resp.dataFim)
        self.assertEqual(resp.pendencias, [])

    def test_response_incompleta_com_pendencias(self):
        resp = InterpretacaoRegraResponse(
            canal=None,
            taxa=None,
            dataInicio=None,
            dataFim=None,
            confianca=Decimal("0.30"),
            pendencias=[
                "Canal de vendas não identificado.",
                "Percentual de comissão não identificado.",
            ],
        )
        self.assertIsNone(resp.canal)
        self.assertIsNone(resp.taxa)
        self.assertIsNone(resp.dataInicio)
        self.assertIsNone(resp.dataFim)
        self.assertEqual(len(resp.pendencias), 2)

    def test_taxa_invalida_zero_ou_negativa(self):
        with self.assertRaises(ValidationError):
            InterpretacaoRegraResponse(taxa=Decimal("0"))

        with self.assertRaises(ValidationError):
            InterpretacaoRegraResponse(taxa=Decimal("-0.05"))

    def test_taxa_invalida_maior_que_um(self):
        with self.assertRaises(ValidationError):
            InterpretacaoRegraResponse(taxa=Decimal("1.0001"))

        with self.assertRaises(ValidationError):
            InterpretacaoRegraResponse(taxa=Decimal("5.0"))

    def test_taxa_valida_limite_um(self):
        resp = InterpretacaoRegraResponse(taxa=Decimal("1.0000"))
        self.assertEqual(resp.taxa, Decimal("1.0000"))

    def test_confianca_invalida(self):
        with self.assertRaises(ValidationError):
            InterpretacaoRegraResponse(confianca=Decimal("-0.1"))

        with self.assertRaises(ValidationError):
            InterpretacaoRegraResponse(confianca=Decimal("1.1"))

    def test_datas_invalidas_fim_anterior_a_inicio(self):
        with self.assertRaises(ValidationError):
            InterpretacaoRegraResponse(
                dataInicio=date(2026, 12, 31),
                dataFim=date(2026, 12, 1),
            )

    def test_serializacao_json(self):
        resp = InterpretacaoRegraResponse(
            canal="ECOMMERCE",
            taxa=Decimal("0.0500"),
            dataInicio=date(2026, 12, 1),
            dataFim=date(2026, 12, 31),
            confianca=Decimal("0.95"),
            pendencias=[],
        )
        json_data = resp.model_dump(mode="json")
        self.assertEqual(json_data["canal"], "ECOMMERCE")
        self.assertEqual(float(json_data["taxa"]), 0.05)
        self.assertEqual(json_data["dataInicio"], "2026-12-01")
        self.assertEqual(json_data["dataFim"], "2026-12-31")
        self.assertEqual(float(json_data["confianca"]), 0.95)
        self.assertEqual(json_data["pendencias"], [])


if __name__ == "__main__":
    unittest.main()
