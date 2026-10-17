"""
Casos de ouro compartilhados com o Spring: o template roda no sandbox e precisa
produzir os mesmos números que o `CalculoService`.

Escopo da simulação: só regras das propostas. Onde o Spring cai na base de comissão ou impede o
cálculo, a simulação deixa a venda "sem regra"/"em conflito" (documentado em templates.py).
"""

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from app.core.simulacao.sandbox import Sandbox
from app.core.simulacao.templates import TEMPLATE_CODIGO

GOLDEN = json.loads((Path(__file__).parent / "golden" / "golden_cases.json").read_text(encoding="utf-8"))


def regra_sandbox(r):
    faixa = None
    if r.get("valorMin") is not None or r.get("valorMax") is not None:
        faixa = {"min": r.get("valorMin"), "max": r.get("valorMax"),
                 "minInclusivo": r.get("minInclusivo", True), "maxInclusivo": r.get("maxInclusivo", True)}
    bonus = None
    if r.get("bonusPercentual") is not None or r.get("bonusValorFixo") is not None:
        bonus = {"percentual": r.get("bonusPercentual"), "valorFixo": r.get("bonusValorFixo")}
    return {
        "idLocal": r["ref"], "taxa": r["taxa"], "bonus": bonus,
        "dataInicio": r["dataInicio"], "dataFim": r["dataFim"],
        "condicoes": {"canal": r.get("canal"), "codMarca": r.get("codMarca"), "codCargo": r.get("codCargo"),
                      "codLoja": r.get("codLoja"), "matricula": r.get("matricula"), "faixaValor": faixa},
    }


def venda_sandbox(v):
    return {"id": "v", "matricula": v["matricula"], "codLoja": v["codLoja"], "codMarca": v["codMarca"],
            "codCargo": v["codCargo"], "valorVenda": v["valor"], "dataVenda": v["dataVenda"], "canal": v.get("canal")}


class TestCasosDeOuro(unittest.TestCase):
    def test_arquivo_tem_casos_suficientes(self):
        self.assertGreaterEqual(len(GOLDEN["casos"]), 15)

    def test_template_bate_com_o_spring(self):
        sb = Sandbox()
        for caso in GOLDEN["casos"]:
            with self.subTest(caso=caso["id"]):
                r = sb.executar(
                    TEMPLATE_CODIGO, [venda_sandbox(caso["venda"])], [regra_sandbox(x) for x in caso["regras"]],
                    [{"nome": "ouro", "multiplicadorVendas": "1"}],
                )
                self.assertTrue(r.ok, r.detalhe)
                res = r.resultados[0]
                esp = caso["esperado"]
                if esp["status"] == "SUCESSO" and esp["origemTaxa"] == "REGRA_NEGOCIO":
                    self.assertEqual(res["totalComissao"], esp["comissaoTotal"], caso["descricao"])
                    self.assertEqual(res["porBloco"], {esp["regraAplicada"]: esp["comissaoTotal"]})
                elif esp["status"] == "SUCESSO":  # base: fora do escopo da simulação de propostas
                    self.assertEqual((res["totalComissao"], res["vendasSemRegra"]), ("0.00", 1), caso["descricao"])
                elif "Conflito" in esp["motivoContem"]:
                    self.assertEqual((res["vendasEmConflito"], res["totalComissao"]), (1, "0.00"), caso["descricao"])
                else:
                    self.assertEqual(res["vendasSemRegra"], 1, caso["descricao"])


if __name__ == "__main__":
    unittest.main()
