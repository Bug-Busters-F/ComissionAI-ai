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

    def test_request_valido_com_contexto_legado(self):
        req = InterpretacaoRegraRequest(
            texto="Pagar 5% no canal ecommerce durante dezembro",
            contexto={"canal_padrao": "ECOMMERCE", "ano_referencia": 2026},
        )
        self.assertEqual(req.texto, "Pagar 5% no canal ecommerce durante dezembro")
        self.assertEqual(req.contexto["canal_padrao"], "ECOMMERCE")
        self.assertEqual(req.contexto["ano_referencia"], 2026)

    def test_request_valido_com_dicionario_dimensoes(self):
        req = InterpretacaoRegraRequest(
            texto="Comissão de 3.5% para os vendedores da marca PRETO na loja 75 em outubro de 2026",
            contexto={
                "ano_referencia": 2026,
                "dicionario_dimensoes": {
                    "marcas": {"10": "PRETO", "20": "BRANCO"},
                    "cargos": {"100": "VENDEDOR LOJA", "150": "GERENTE DE LOJA"},
                    "canais": ["LOJA_FISICA", "ECOMMERCE", "BALCAO"],
                },
            },
        )
        self.assertEqual(req.contexto["dicionario_dimensoes"]["marcas"]["10"], "PRETO")
        self.assertEqual(req.contexto["dicionario_dimensoes"]["cargos"]["100"], "VENDEDOR LOJA")
        self.assertIn("LOJA_FISICA", req.contexto["dicionario_dimensoes"]["canais"])

    def test_request_sem_contexto_usa_default(self):
        req = InterpretacaoRegraRequest(texto="Pagar 3% no canal loja_fisica")
        self.assertEqual(req.texto, "Pagar 3% no canal loja_fisica")
        self.assertEqual(req.contexto, {})

    def test_request_sem_texto_lanca_validacao(self):
        with self.assertRaises(ValidationError):
            InterpretacaoRegraRequest()  # type: ignore


class TestInterpretacaoRegraResponse(unittest.TestCase):
    """Testes da proposta de regra estruturada InterpretacaoRegraResponse."""

    def test_response_valida_completa_com_dimensoes(self):
        """Cenário A do contrato: regra completa com marca, cargo e loja."""
        resp = InterpretacaoRegraResponse(
            canal="LOJA_FISICA",
            codMarca=10,
            descrMarca="preto",  # deve ser normalizado para maiúsculas
            codCargo=100,
            descriCargo="vendedor loja",  # deve ser normalizado
            codLoja=75,
            taxa=Decimal("0.0350"),
            dataInicio=date(2026, 10, 1),
            dataFim=date(2026, 10, 31),
            confianca=Decimal("0.95"),
            pendencias=[],
        )
        self.assertEqual(resp.canal, "LOJA_FISICA")
        self.assertEqual(resp.codMarca, 10)
        self.assertEqual(resp.descrMarca, "PRETO")
        self.assertEqual(resp.codCargo, 100)
        self.assertEqual(resp.descriCargo, "VENDEDOR LOJA")
        self.assertEqual(resp.codLoja, 75)
        self.assertEqual(resp.taxa, Decimal("0.0350"))
        self.assertEqual(resp.dataInicio, date(2026, 10, 1))
        self.assertEqual(resp.dataFim, date(2026, 10, 31))
        self.assertEqual(resp.confianca, Decimal("0.95"))
        self.assertEqual(resp.pendencias, [])

    def test_response_valida_sem_dimensoes(self):
        """Cenário B: apenas canal e taxa, sem marca/cargo/loja."""
        resp = InterpretacaoRegraResponse(
            canal="ecommerce ",
            taxa=Decimal("0.0500"),
            dataInicio=date(2026, 12, 1),
            dataFim=date(2026, 12, 31),
            confianca=Decimal("0.95"),
            pendencias=[],
        )
        self.assertEqual(resp.canal, "ECOMMERCE")
        self.assertIsNone(resp.codMarca)
        self.assertIsNone(resp.descrMarca)
        self.assertIsNone(resp.codCargo)
        self.assertIsNone(resp.descriCargo)
        self.assertIsNone(resp.codLoja)

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
        """Cenário C: regra com ambiguidade de cargo e campos faltando."""
        resp = InterpretacaoRegraResponse(
            canal=None,
            codMarca=None,
            descrMarca=None,
            codCargo=None,
            descriCargo=None,
            codLoja=None,
            taxa=None,
            dataInicio=None,
            dataFim=None,
            confianca=Decimal("0.30"),
            pendencias=[
                "Ambiguidade de cargo: 'gerentes' pode referir-se a 'GERENTE DE LOJA' ou 'GERENTE QUIOSQUE'.",
                "Percentual de comissão não identificado.",
                "Data de início da vigência não identificada.",
            ],
        )
        self.assertIsNone(resp.canal)
        self.assertIsNone(resp.codMarca)
        self.assertIsNone(resp.codCargo)
        self.assertIsNone(resp.codLoja)
        self.assertIsNone(resp.taxa)
        self.assertEqual(len(resp.pendencias), 3)

    def test_canal_null_valido(self):
        """canal é nullable conforme correção 2 do banco (tb_regra.canal NULLABLE)."""
        resp = InterpretacaoRegraResponse(canal=None, taxa=Decimal("0.05"), dataInicio=date(2026, 10, 1))
        self.assertIsNone(resp.canal)

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

    def test_serializacao_json_com_todas_dimensoes(self):
        resp = InterpretacaoRegraResponse(
            canal="LOJA_FISICA",
            codMarca=10,
            descrMarca="PRETO",
            codCargo=100,
            descriCargo="VENDEDOR LOJA",
            codLoja=75,
            taxa=Decimal("0.0350"),
            dataInicio=date(2026, 10, 1),
            dataFim=date(2026, 10, 31),
            confianca=Decimal("0.95"),
            pendencias=[],
        )
        json_data = resp.model_dump(mode="json")
        self.assertEqual(json_data["canal"], "LOJA_FISICA")
        self.assertEqual(json_data["codMarca"], 10)
        self.assertEqual(json_data["descrMarca"], "PRETO")
        self.assertEqual(json_data["codCargo"], 100)
        self.assertEqual(json_data["descriCargo"], "VENDEDOR LOJA")
        self.assertEqual(json_data["codLoja"], 75)
        self.assertAlmostEqual(float(json_data["taxa"]), 0.035, places=4)
        self.assertEqual(json_data["dataInicio"], "2026-10-01")
        self.assertEqual(json_data["dataFim"], "2026-10-31")
        self.assertEqual(float(json_data["confianca"]), 0.95)
        self.assertEqual(json_data["pendencias"], [])

    def test_serializacao_json_sem_dimensoes(self):
        resp = InterpretacaoRegraResponse(
            canal="ECOMMERCE",
            taxa=Decimal("0.0500"),
            dataInicio=date(2026, 12, 1),
            dataFim=date(2026, 12, 31),
            confianca=Decimal("0.95"),
            pendencias=[],
        )
        json_data = resp.model_dump(mode="json")
        self.assertIsNone(json_data["codMarca"])
        self.assertIsNone(json_data["descrMarca"])
        self.assertIsNone(json_data["codCargo"])
        self.assertIsNone(json_data["descriCargo"])
        self.assertIsNone(json_data["codLoja"])


if __name__ == "__main__":
    unittest.main()
