"""Testes do IA-8 (BUG-121): detecção estatística diária de anomalias por grupo comparável."""

import csv
import os
import random
import sys
import time
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from app.core.anomalias.iqr import faixa_iqr, quantil  # noqa: E402
from app.core.anomalias.servico import analisar  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas.anomalia import AnalisarAnomaliasRequest  # noqa: E402

D = Decimal
COMP = "2025-11"
BASES = Path(__file__).resolve().parents[1] / "data" / "bases_limpas" / "csv"


def venda(id_, mat, valor, dia=1, marca=10, cargo=100, descr="VENDEDOR LOJA", comp=COMP):
    return {"id": id_, "matricula": mat, "codLoja": 1, "codMarca": marca, "codCargo": cargo,
            "descriCargo": descr, "valorVenda": str(valor), "dataVenda": f"{comp}-{dia:02d}"}


def grupo_normal(n=10, base=1000, passo=50, **kw):
    """n colaboradores com totais 1000, 1050, 1100… num único dia."""
    return [venda(f"v{i}", f"M{i}", base + i * passo, **kw) for i in range(n)]


def rodar(vendas, **kw):
    return analisar(AnalisarAnomaliasRequest(competencia=COMP, vendas=vendas, **kw))


class TestQuartis(unittest.TestCase):
    def test_interpolacao_linear_inclusiva(self):
        v = [D(1), D(2), D(3), D(4)]  # QUARTIL.INC: 1,75 / 2,5 / 3,25
        self.assertEqual([quantil(v, D(p)) for p in ("0.25", "0.5", "0.75")], [D("1.75"), D("2.5"), D("3.25")])

    def test_faixa_reproduzivel_a_partir_da_evidencia(self):
        f = faixa_iqr([D(x) for x in (10, 20, 30, 40, 50)], D("1.5"))
        self.assertEqual((f.q1, f.q3, f.iqr), (D("20.00"), D("40.00"), D("20.00")))
        self.assertEqual((f.minimo, f.maximo), (D("-10.00"), D("70.00")))


class TestDeteccao(unittest.TestCase):
    def test_alerta_com_valor_faixa_grupo_e_evidencia(self):
        r = rodar(grupo_normal() + [venda("x", "MX", 9000)])
        self.assertEqual(len(r.alertas), 1)
        a = r.alertas[0]
        self.assertEqual((a.tipo, a.matricula, a.valorObservado, a.tamanhoAmostra), ("ACIMA_DA_FAIXA", "MX", D("9000"), 11))
        self.assertEqual((a.grupo.codMarca, a.grupo.codCargo, a.grupo.descriCargo, a.grupo.competencia),
                         (10, 100, "VENDEDOR LOJA", COMP))
        e = a.evidencia
        self.assertEqual(a.faixaEsperada.max, (e.q3 + D("1.5") * e.iqr).quantize(D("0.01")))
        self.assertEqual(a.distanciaFaixa, a.valorObservado - a.faixaEsperada.max)
        self.assertEqual(a.vendaIds, ["x"])
        self.assertIn("Conferir", a.explicacao)

    def test_soma_por_colaborador_e_dia(self):
        r = rodar(grupo_normal() + [venda("x1", "MX", 4500, dia=3), venda("x2", "MX", 4500, dia=3)])
        a = r.alertas[0]
        self.assertEqual((a.valorObservado, a.qtdVendas, sorted(a.vendaIds)), (D("9000"), 2, ["x1", "x2"]))
        self.assertEqual(a.data.day, 3)

    def test_abaixo_da_faixa(self):
        vendas = [venda(f"v{i}", f"M{i}", 1000 + i * 10) for i in range(12)] + [venda("neg", "MN", -2000)]
        r = rodar(vendas)
        self.assertEqual([(a.tipo, a.matricula) for a in r.alertas], [("ABAIXO_DA_FAIXA", "MN")])
        a = r.alertas[0]
        self.assertEqual(a.faixaEsperada.min, (a.evidencia.q1 - D("1.5") * a.evidencia.iqr).quantize(D("0.01")))
        self.assertEqual(a.distanciaFaixa, a.faixaEsperada.min - a.valorObservado)

    def test_grupo_com_negativos_mantem_limite_inferior_negativo(self):
        vendas = [venda(f"v{i}", f"M{i}", -500 + i * 300) for i in range(10)]
        g = rodar(vendas).grupos[0]
        self.assertEqual(g.faixaEsperada.min, (g.evidencia.q1 - D("1.5") * g.evidencia.iqr).quantize(D("0.01")))
        self.assertLess(g.faixaEsperada.min, 0)

    def test_limite_inferior_nao_fica_negativo_sem_valores_negativos(self):
        r = rodar(grupo_normal(base=100, passo=400))
        self.assertEqual(r.grupos[0].faixaEsperada.min, D("0.00"))
        self.assertLess(r.grupos[0].evidencia.q1 - D("1.5") * r.grupos[0].evidencia.iqr, 0)

    def test_grupos_por_descricao_do_cargo(self):
        """150 = GERENTE DE LOJA e GERENTE QUIOSQUE: grupos distintos, sem misturar escalas."""
        loja = grupo_normal(cargo=150, descr="GERENTE DE LOJA", base=20000, passo=500)
        quiosque = [venda(f"q{i}", f"Q{i}", 3000 + i * 50, cargo=150, descr="gerente  quiosque") for i in range(10)]
        r = rodar(loja + quiosque)
        self.assertEqual([g.grupo.descriCargo for g in r.grupos], ["GERENTE DE LOJA", "GERENTE QUIOSQUE"])
        self.assertEqual(r.alertas, [])  # misturados, os quiosques seriam "anomalias" baixas


class TestProtecoes(unittest.TestCase):
    def test_grupo_pequeno_nao_gera_alerta(self):
        r = rodar([venda("a", "A", 100), venda("b", "B", 100000)])
        g = r.grupos[0]
        self.assertEqual((g.status, g.tamanhoAmostra, g.faixaEsperada), ("AMOSTRA_INSUFICIENTE", 2, None))
        self.assertEqual(r.alertas, [])
        self.assertIn("mínimo para avaliar: 8", g.motivo)

    def test_valores_repetidos_iqr_zero(self):
        r = rodar([venda(f"v{i}", f"M{i}", 500) for i in range(10)] + [venda("x", "X", 50000)])
        self.assertEqual((r.grupos[0].status, r.alertas), ("SEM_VARIACAO", []))
        self.assertEqual(r.resumo.gruposSemVariacao, 1)

    def test_dias_sem_venda_nao_viram_zero(self):
        """Cada colaborador vende em um dia diferente; preencher zeros geraria alertas em todos."""
        vendas = [venda(f"v{i}", f"M{i}", 1000 + i * 20, dia=i + 1) for i in range(10)]
        r = rodar(vendas)
        self.assertEqual(r.grupos[0].tamanhoAmostra, 10)
        self.assertEqual(r.alertas, [])
        self.assertEqual((r.cobertura.diasNaCompetencia, r.cobertura.diasSemCobertura), (30, 20))
        self.assertTrue(any("não foram tratados como venda zero" in o for o in r.observacoes))

    def test_venda_sem_rh_e_erro_de_carga(self):
        rh = [{"matricula": f"M{i}", "codCargo": 100, "descriCargo": "VENDEDOR LOJA"} for i in range(10)]
        vendas = [dict(venda(f"v{i}", f"m{i} ", 1000 + i * 50), codCargo=None, descriCargo=None) for i in range(10)]
        vendas += [venda("fant", "FANTASMA", 999999), venda("out", "M1", 50, comp="2025-10")]
        r = rodar(vendas, dadosRh=rh)
        self.assertEqual(r.grupos[0].tamanhoAmostra, 10)  # cargo veio do RH (matrícula normalizada)
        erros = {e.codigo: e for e in r.errosCarga}
        self.assertEqual(erros["VENDA_SEM_RH"].vendaIds, ["fant"])
        self.assertEqual(erros["FORA_DA_COMPETENCIA"].quantidade, 1)
        self.assertEqual(r.alertas, [])  # a venda sem RH não vira alerta
        self.assertEqual(r.resumo.vendasComErroCarga, 2)

    def test_sem_marca(self):
        r = rodar(grupo_normal() + [dict(venda("s", "S", 10), codMarca=None)])
        self.assertEqual([e.codigo for e in r.errosCarga], ["VENDA_SEM_MARCA"])


class TestReprodutibilidade(unittest.TestCase):
    def test_mesma_entrada_mesmo_hash_e_resultado_em_qualquer_ordem(self):
        vendas = grupo_normal() + [venda("x", "MX", 9000)]
        r1 = rodar(vendas)
        embaralhadas = vendas[:]
        random.Random(7).shuffle(embaralhadas)
        r2 = rodar(embaralhadas)
        self.assertEqual(r1.versaoDados, r2.versaoDados)
        self.assertEqual(r1.model_dump(), r2.model_dump())

    def test_parametros_explicitos_mudam_metodo_e_hash(self):
        vendas = grupo_normal() + [venda("x", "MX", 2000)]
        padrao = rodar(vendas)
        frouxo = rodar(vendas, parametros={"k": "3", "amostraMinima": 5})
        self.assertEqual((padrao.metodo.k, padrao.metodo.amostraMinima), (D("1.5"), 8))
        self.assertEqual((frouxo.metodo.k, frouxo.metodo.amostraMinima), (D("3"), 5))
        self.assertNotEqual(padrao.versaoDados, frouxo.versaoDados)
        self.assertLessEqual(len(frouxo.alertas), len(padrao.alertas))

    def test_ids_estaveis(self):
        vendas = grupo_normal() + [venda("x", "MX", 9000)]
        self.assertEqual(rodar(vendas).alertas[0].id, rodar(vendas).alertas[0].id)

    def test_texto_orienta_conferir_e_nao_corrige(self):
        r = rodar(grupo_normal() + [venda("x", "MX", 9000)], versaoFontes={"hashRecorte": "abc"},
                  contexto={"execucaoId": "e1"})
        self.assertEqual((r.tipo, r.granularidade, r.execucaoId), ("INDICIO_PARA_CONFERENCIA", "DIARIA", "e1"))
        self.assertEqual(r.versaoFontes, {"hashRecorte": "abc"})
        self.assertIn("conferência", r.aviso)
        self.assertIn("Nenhuma venda foi alterada", r.explicacao)


class TestDesempenho(unittest.TestCase):
    def test_trinta_mil_vendas(self):
        rnd = random.Random(1)
        vendas = [venda(f"v{i}", f"M{i % 900}", rnd.randint(100, 5000), dia=rnd.randint(1, 30),
                        marca=10 * (1 + i % 5), cargo=100 + 50 * (i % 3), descr=f"C{i % 3}")
                  for i in range(30000)]
        t0 = time.perf_counter()
        r = rodar(vendas)
        self.assertLess(time.perf_counter() - t0, 10)
        self.assertEqual(r.resumo.vendasAnalisadas, 30000)


class TestRota(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_analisar(self):
        corpo = {"competencia": COMP, "vendas": grupo_normal() + [venda("x", "MX", 9000)]}
        r = self.client.post("/api/v2/anomalias/analisar", json=corpo)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["alertas"][0]["matricula"], "MX")

    def test_volume_excedido(self):
        with patch.object(settings, "anomalia_max_vendas", 5):
            r = self.client.post("/api/v2/anomalias/analisar", json={"competencia": COMP, "vendas": grupo_normal()})
        self.assertEqual(r.status_code, 413)

    def test_competencia_invalida(self):
        r = self.client.post("/api/v2/anomalias/analisar", json={"competencia": "11/2025", "vendas": []})
        self.assertEqual(r.status_code, 422)


@unittest.skipUnless((BASES / "VENDAS_2025-07.csv").exists(), "bases limpas do IA-9 ausentes (não versionadas)")
class TestBaseRealJulho(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        def ler(nome):
            with (BASES / nome).open(encoding="utf-8-sig") as f:
                return list(csv.DictReader(f, delimiter=";"))

        rh = [{"matricula": r["Matricula"], "codCargo": int(r["Cod_Cargo"]), "descriCargo": r["Descri_Cargo"]}
              for r in ler("RH_2025-07.csv")]
        vendas = [{"id": f"v{i}", "matricula": v["Matricula"], "codMarca": int(v["Cod_Marca"]),
                   "valorVenda": v["Vlr_Venda"], "dataVenda": v["Date_Ref"][:10]}
                  for i, v in enumerate(ler("VENDAS_2025-07.csv"))]
        cls.r = analisar(AnalisarAnomaliasRequest(competencia="2025-07", vendas=vendas, dadosRh=rh))

    def test_alertas_reais(self):
        self.assertEqual(self.r.resumo.vendasComErroCarga, 0)
        self.assertIn("MATRIC-141", {a.matricula for a in self.r.alertas})  # R$ 113.627,50 no VENDEDOR BALCAO

    def test_venda_isolada_alta_nao_e_anomalia_no_total_do_dia(self):
        """A venda de R$ 78.542 (MATRIC-543) soma R$ 85.000 no dia, dentro da faixa do VENDEDOR LOJA."""
        self.assertNotIn("MATRIC-543", {a.matricula for a in self.r.alertas})

    def test_dia_unico_informado(self):
        self.assertTrue(any("01/07/2025" in o for o in self.r.observacoes))


if __name__ == "__main__":
    unittest.main()
