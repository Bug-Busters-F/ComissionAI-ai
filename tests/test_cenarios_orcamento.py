"""
Testes do IA-5 (BUG-118): quatro cenários, custo contratual x proposto, projeção e enquadramento orçamentário.

Os valores esperados foram calculados à mão com as regras do `SimulacaoCenariosService` do backend
(BACK-8): população pelo público das regras, fallback contratual fora da faixa, HALF_UP escala 2,
fator de projeção = dias inclusivos ÷ 30 (escala 6) e enquadramento pelo custo projetado.
"""

import os
import sys
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import httpx
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from app.api.routes.v2 import get_simulador  # noqa: E402
from app.core.simulacao.cenarios import (  # noqa: E402
    ResolvedorTaxa,
    consolidar,
    periodo_projecao,
    preparar_populacao,
)
from app.core.simulacao.servico import ServicoSimulacao  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas.proposta import (  # noqa: E402
    BlocoProposta,
    Cenario,
    Condicoes,
    FaixaValor,
    PeriodoCampanha,
    ResultadoCenario,
    SimularRequest,
    TaxaContratual,
)
from app.tools import BackendClient, criar_registry  # noqa: E402

D = Decimal
TAXAS = [
    {"codMarca": 10, "codCargo": 100, "descriCargo": "VENDEDOR LOJA", "taxa": "0.025"},
    {"codMarca": 10, "codCargo": 150, "descriCargo": "GERENTE DE LOJA", "taxa": "0.01"},
    {"codMarca": 10, "codCargo": 150, "descriCargo": "GERENTE QUIOSQUE", "taxa": "0.015"},
]


def registry_sem_chamadas():
    def h(req: httpx.Request):
        raise AssertionError(f"Consulta inesperada ao backend: {req.url.path}")

    c = BackendClient(base_url="http://b", timeout=1, transport=httpx.MockTransport(h))
    c.RETRY_BACKOFF_SECONDS = 0
    return criar_registry(c, incluir_simulacao=True)


def sem_llm():
    p = MagicMock()
    p.complete.side_effect = AssertionError("o IA-5 não usa LLM")
    return p


def venda(id_, valor, loja=75, marca=10, cargo=100, descr="VENDEDOR LOJA", data="2026-12-10", mat=None, **kw):
    return {"id": id_, "matricula": mat or f"M-{id_}", "codLoja": loja, "codMarca": marca, "codCargo": cargo,
            "descriCargo": descr, "valorVenda": str(valor), "dataVenda": data, "canal": None, **kw}


def regra(id_, taxa, faixa=None, inicio=date(2026, 12, 1), fim=date(2026, 12, 31), **cond):
    return BlocoProposta(idLocal=id_, condicoes=Condicoes(faixaValor=faixa, **cond), taxa=D(taxa),
                         dataInicio=inicio, dataFim=fim)


P1 = regra("p1", "0.05", faixa=FaixaValor(min=D("1000"), minInclusivo=True), codLoja=75)
# a: 1000 (faixa da p1), b: 500 (público da p1, fora da faixa -> fallback contratual), c: loja 99 (fora do público)
VENDAS = [venda("a", "1000.00"), venda("b", "500.00"), venda("c", "800.00", loja=99)]
QUINZENA = {"dataInicio": "2026-12-01", "dataFim": "2026-12-15"}  # 15 dias -> fator 0.5


def simular(propostas=(P1,), vendas=VENDAS, **kw):
    kw.setdefault("taxasContratuais", TAXAS)
    req = SimularRequest(propostas=list(propostas), competencia="2026-12", vendas=vendas, **kw)
    return ServicoSimulacao(sem_llm(), registry_sem_chamadas()).simular(req)


class TestQuatroCenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = simular(orcamento="40", periodoCampanha=QUINZENA)

    def cenario(self, mult):
        return next(x for x in self.r.resultados if x.multiplicadorVendas == D(mult))

    def test_quatro_cenarios_padrao_sem_llm(self):
        self.assertEqual([x.cenario for x in self.r.resultados],
                         ["Vendas 80%", "Vendas 100%", "Vendas 120%", "Vendas 150%"])
        self.assertEqual(self.r.pendencias, [])

    def test_cenario_100_custos_e_fallback(self):
        c = self.cenario("1")
        self.assertEqual(c.porBloco, {"p1": D("50.00"), "BASE_CONTRATUAL": D("12.50")})
        self.assertEqual(c.totalComissao, D("62.50"))
        self.assertEqual(c.custoContratual, D("37.50"))  # 1000×2,5% + 500×2,5%
        self.assertEqual((c.diferenca, c.diferencaPercentual), (D("25.00"), D("66.67")))
        self.assertEqual((c.qtdVendas, c.qtdRegraAplicada, c.qtdFallbackContratual), (2, 1, 1))
        self.assertEqual(c.totalVendas, D("1500.00"))  # a venda fora do público não entra no escopo

    def test_faixas_reavaliadas_pelo_volume(self):
        c80 = self.cenario("0.8")  # a: 800 sai da faixa da p1 -> contratual
        self.assertEqual(c80.porBloco, {"BASE_CONTRATUAL": D("30.00")})
        self.assertEqual((c80.qtdMudancaFaixa, c80.diferenca), (1, D("0.00")))
        c150 = self.cenario("1.5")
        self.assertEqual(c150.totalComissao, D("93.75"))  # 1500×5% + 750×2,5%
        self.assertEqual((c150.custoContratual, c150.qtdMudancaFaixa), (D("56.25"), 0))

    def test_projecao_pelo_periodo_da_campanha(self):
        self.assertEqual(self.cenario("1").fatorProjecao, D("0.500000"))
        self.assertEqual(self.cenario("1").custoProjetado, D("31.25"))
        self.assertEqual(self.cenario("1.5").custoProjetado, D("46.88"))  # 46,875 HALF_UP
        self.assertEqual(self.cenario("1").deltaProjetado, D("12.50"))

    def test_enquadramento_por_cenario(self):
        e100 = self.cenario("1").enquadramento
        self.assertEqual((e100.statusEnquadramento, e100.dentroDoOrcamento), ("ENQUADRADO", True))
        self.assertEqual((e100.saldoOrcamento, e100.excedenteOrcamento, e100.percentualUsoOrcamento),
                         (D("8.75"), D("0.00"), D("78.13")))
        e150 = self.cenario("1.5").enquadramento
        self.assertEqual((e150.statusEnquadramento, e150.excedenteOrcamento), ("ACIMA_DO_TETO", D("6.88")))

    def test_resumo_usa_o_cenario_100_para_encaminhar(self):
        o = self.r.orcamento
        self.assertEqual((o.valorEncaminhamento, o.statusCenario100), (D("31.25"), "ENQUADRADO"))
        self.assertTrue(o.aptoEncaminhamentoGerente)
        self.assertIsNone(o.motivoBloqueioEncaminhamento)
        self.assertEqual((o.diasInclusivos, o.totalVendasEscopoComum), (15, 2))

    def test_fora_do_publico_e_explicitado_sem_bloquear(self):
        ex = {e.codigo: e for e in self.r.exclusoes}
        self.assertEqual(set(ex), {"FORA_DO_PUBLICO"})
        self.assertEqual((ex["FORA_DO_PUBLICO"].quantidade, ex["FORA_DO_PUBLICO"].vendaIds), (1, ["c"]))
        self.assertFalse(ex["FORA_DO_PUBLICO"].impedeEncaminhamento)

    def test_reconciliacao_das_partes(self):
        for c in self.r.resultados:
            self.assertEqual(sum(c.porBloco.values()), c.totalComissao)
            self.assertEqual(sum(c.porMatricula.values()), c.totalComissao)


class TestBloqueiosDeEncaminhamento(unittest.TestCase):
    def test_cenario_100_acima_do_teto(self):
        r = simular(orcamento="30", periodoCampanha=QUINZENA)
        self.assertEqual(r.orcamento.statusCenario100, "ACIMA_DO_TETO")
        self.assertFalse(r.orcamento.aptoEncaminhamentoGerente)
        self.assertIn("excede o teto", r.orcamento.motivoBloqueioEncaminhamento)
        self.assertIn("R$ 31,25", r.orcamento.motivoBloqueioEncaminhamento)

    def test_sem_orcamento(self):
        r = simular(periodoCampanha=QUINZENA)
        self.assertEqual(r.orcamento.statusCenario100, "NAO_APLICAVEL")
        self.assertEqual(r.resultados[1].enquadramento.statusEnquadramento, "NAO_APLICAVEL")
        self.assertFalse(r.orcamento.aptoEncaminhamentoGerente)
        self.assertEqual(r.orcamento.motivoBloqueioEncaminhamento, "Orçamento monetário não informado.")

    def test_venda_sem_taxa_contratual_nao_vira_zero(self):
        vendas = VENDAS + [venda("d", "200.00", marca=20)]  # marca 20 sem taxa
        r = simular(vendas=vendas, orcamento="1000")
        ex = {e.codigo: e for e in r.exclusoes}
        self.assertEqual((ex["SEM_TAXA_CONTRATUAL"].quantidade, ex["SEM_TAXA_CONTRATUAL"].valorVendas),
                         (1, D("200.00")))
        self.assertTrue(ex["SEM_TAXA_CONTRATUAL"].impedeEncaminhamento)
        self.assertEqual(r.resultados[1].qtdVendas, 2)
        self.assertFalse(r.orcamento.aptoEncaminhamentoGerente)
        self.assertIn("não calculável", r.orcamento.motivoBloqueioEncaminhamento)

    def test_conflito_de_regras_bloqueia(self):
        r = simular(propostas=[regra("p1", "0.02", codLoja=75), regra("p2", "0.03", codLoja=75)], orcamento="1000")
        ex = {e.codigo: e for e in r.exclusoes}
        self.assertEqual(ex["CONFLITO_REGRAS"].quantidade, 2)
        self.assertFalse(r.orcamento.aptoEncaminhamentoGerente)
        self.assertEqual(r.resultados[1].totalComissao, D("0.00"))

    def test_conflito_fica_fora_dos_dois_lados_da_diferenca(self):
        """Venda em conflito não entra no custo proposto; também não pode entrar no custo contratual."""
        propostas = [regra("p1", "0.02", codLoja=75), regra("p2", "0.03", codLoja=75), regra("p3", "0.04", codLoja=76)]
        vendas = [venda("a", "1000.00"), venda("b", "500.00"), venda("d", "2000.00", loja=76)]
        c100 = simular(propostas=propostas, vendas=vendas).resultados[1]
        self.assertEqual(c100.qtdConflito, 2)
        self.assertEqual(c100.totalComissao, D("80.00"))  # só d: 2000 × 4%
        self.assertEqual(c100.custoContratual, D("50.00"))  # só d: 2000 × 2,5% (antes: 87,50 com a e b)
        self.assertEqual(c100.diferenca, D("30.00"))

    def test_conflito_sem_parcela_contratual_nao_devolve_diferenca(self):
        """Código livre que conta conflitos sem informar `contratualEmConflito`: sem diferença inventada."""
        pop = preparar_populacao([venda("a", "100"), venda("b", "100")], [regra("p1", "0.1", codLoja=75)],
                                 [TaxaContratual(**TAXAS[0])])
        res = [ResultadoCenario(cenario="x", totalVendas=D("200.00"), totalComissao=D("10.00"))]
        bruto = [{"vendasComRegra": 1, "vendasFallbackContratual": 0, "vendasEmConflito": 1, "vendasSemRegra": 0,
                  "vendasMudancaFaixa": 0}]
        c = consolidar(res, bruto, [Cenario(nome="x")], pop, D("100"), None, "2026-12")
        self.assertIsNone(c.erro)
        self.assertIsNone(c.resultados[0].custoContratual)
        self.assertIsNone(c.resultados[0].diferenca)


class TestTaxaContratual(unittest.TestCase):
    def test_codigo_150_resolvido_pela_descricao(self):
        r = ResolvedorTaxa([TaxaContratual(**t) for t in TAXAS])
        self.assertEqual(r.resolver(10, 150, "gerente  quiosque"), (D("0.015"), None))
        self.assertEqual(r.resolver(10, 150, None), (None, "TAXA_CONTRATUAL_AMBIGUA"))
        self.assertEqual(r.resolver(10, 100, None), (D("0.025"), None))  # par com taxa única
        self.assertEqual(r.resolver(30, 100, "VENDEDOR LOJA"), (None, "SEM_TAXA_CONTRATUAL"))

    def test_gerente_sem_descricao_e_excluido_como_ambiguo(self):
        p = regra("p1", "0.05", codLoja=75)
        r = simular(propostas=[p], vendas=[venda("a", "100", cargo=150, descr=None), venda("b", "100")])
        self.assertEqual([e.codigo for e in r.exclusoes], ["TAXA_CONTRATUAL_AMBIGUA"])

    def test_taxa_da_venda_enviada_pelo_backend_tem_precedencia(self):
        p = regra("p1", "0.05", faixa=FaixaValor(min=D("5000")), codLoja=75)
        r = simular(propostas=[p], vendas=[venda("a", "1000.00", taxaContratual="0.04")])
        self.assertEqual(r.resultados[1].porBloco, {"BASE_CONTRATUAL": D("40.00")})

    def test_alias_percentual_do_backend(self):
        t = TaxaContratual.model_validate({"codMarca": 10, "codCargo": 100, "percentual": "0.02", "taxa": "0.02",
                                           "idLoteOrigem": "x"})
        self.assertEqual(t.taxa, D("0.02"))

    def test_sem_taxas_mantem_contrato_anterior(self):
        r = simular(taxasContratuais=[])
        c = r.resultados[1]
        self.assertIsNone(c.custoContratual)
        self.assertEqual(c.porBloco, {"p1": D("50.00")})  # b fica sem comissão, como antes do IA-5
        self.assertTrue(any("Taxas contratuais não informadas" in o for o in r.observacoes))
        self.assertTrue(any("sem regra aplicável nem taxa contratual" in o for o in r.observacoes))


class TestReferenciaHistorica(unittest.TestCase):
    def test_vigencia_da_regra_nao_filtra_vendas_historicas(self):
        """Campanha de 2026 simulada sobre vendas de 2025 (igual ao backend): a regra se aplica."""
        vendas = [venda("a", "2000.00", data="2025-11-01")]
        req = SimularRequest(propostas=[P1], competencia="2025-11", vendas=vendas, taxasContratuais=TAXAS,
                             periodoCampanha={"dataInicio": "2026-12-01", "dataFim": "2026-12-31"})
        r = ServicoSimulacao(sem_llm(), registry_sem_chamadas()).simular(req)
        self.assertEqual(r.resultados[1].porBloco, {"p1": D("100.00")})
        self.assertEqual(r.resultados[1].fatorProjecao, D("1.033333"))  # 31 dias ÷ 30

    def test_sem_periodo_usa_mes_da_competencia(self):
        self.assertEqual(periodo_projecao(None, "2026-02")[2:], (28, D("0.933333")))
        self.assertEqual(periodo_projecao(PeriodoCampanha(dataInicio=date(2026, 1, 1), dataFim=date(2026, 1, 30)),
                                          "2026-01")[2:], (30, D("1.000000")))


class TestReconciliacao(unittest.TestCase):
    def test_contagem_de_vendas_que_nao_fecha_descarta_os_numeros(self):
        pop = preparar_populacao([venda("a", "100"), venda("b", "100")], [regra("p1", "0.1", codLoja=75)],
                                 [TaxaContratual(**TAXAS[0])])
        res = [ResultadoCenario(cenario="x", totalVendas=D("200.00"), totalComissao=D("20.00"))]
        bruto = [{"vendasComRegra": 1, "vendasFallbackContratual": 0, "vendasEmConflito": 0, "vendasSemRegra": 0,
                  "vendasMudancaFaixa": 0}]
        c = consolidar(res, bruto, [Cenario(nome="x")], pop, None, None, "2026-12")
        self.assertIsNotNone(c.erro)
        self.assertEqual(c.resultados, [])

    def test_servico_nao_devolve_numeros_quando_a_reconciliacao_falha(self):
        codigo = (
            "from decimal import Decimal\n"
            "def simular(vendas, regras, cenario):\n"
            "    t = Decimal('0.00')\n"
            "    for v in vendas:\n"
            "        t += (v['valorVenda'] * cenario['multiplicadorVendas']).quantize(Decimal('0.01'))\n"
            "    return {'cenario': cenario['nome'], 'totalVendas': t, 'totalComissao': Decimal('0.00'),\n"
            "            'porBloco': {}, 'porMatricula': {}, 'vendasComRegra': 0, 'vendasFallbackContratual': 0,\n"
            "            'vendasEmConflito': 0, 'vendasSemRegra': 0, 'vendasMudancaFaixa': 0}\n"
        )
        r = simular(codigoAprovado=codigo, orcamento="100")
        self.assertEqual(r.resultados, [])
        self.assertIsNone(r.orcamento)
        self.assertTrue(any("não somam" in p.mensagem for p in r.pendencias))

    def test_riscos_das_pendencias_aceitas(self):
        r = simular(orcamento="100", pendenciasAceitas=[{"tipoBase": "VENDAS", "linha": 3, "motivo": "x"},
                                                        {"tipoBase": "RH", "linha": 9, "motivo": "y"}])
        self.assertEqual(len(r.riscos), 1)
        self.assertIn("2 pendência(s)", r.riscos[0])


class TestRota(unittest.TestCase):
    def test_contrato_json_com_nomes_do_backend(self):
        app.dependency_overrides[get_simulador] = lambda: ServicoSimulacao(sem_llm(), registry_sem_chamadas())
        try:
            corpo = {"propostas": [P1.model_dump(mode="json")], "competencia": "2026-12", "vendas": VENDAS,
                     "taxasContratuais": [{**t, "percentual": t["taxa"]} for t in TAXAS], "orcamento": "40",
                     "periodoCampanha": QUINZENA}
            j = TestClient(app).post("/api/v2/simular", json=corpo).json()
        finally:
            app.dependency_overrides.clear()
        self.assertEqual(len(j["resultados"]), 4)
        e = j["resultados"][1]["enquadramento"]
        self.assertEqual(set(e), {"cenario", "multiplicadorVolume", "totalVendasEscopo", "orcamentoTeto",
                                  "custoTotalProjetado", "deltaProjetado", "statusEnquadramento",
                                  "dentroDoOrcamento", "saldoOrcamento", "excedenteOrcamento",
                                  "percentualUsoOrcamento"})
        self.assertEqual(j["orcamento"]["valorEncaminhamento"], "31.25")
        self.assertTrue(j["orcamento"]["aptoEncaminhamentoGerente"])


if __name__ == "__main__":
    unittest.main()
