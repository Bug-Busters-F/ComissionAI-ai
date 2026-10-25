"""Testes do serviço de simulação (template, código livre, validação e roteamento)."""

import os
import sys
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import httpx
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from app.api.routes.v2 import get_simulador
from app.core.agente import Limites
from app.core.exceptions import LLMAuthenticationError
from app.core.simulacao.servico import ServicoSimulacao
from app.main import app
from app.schemas.proposta import BlocoProposta, Bonus, Condicoes, FaixaValor, SimularRequest
from app.tools import BackendClient, criar_registry

VENDAS = [
    {"id": "a", "matricula": "M1", "codLoja": 75, "codMarca": 10, "codCargo": 100, "valorVenda": "1000.00", "dataVenda": "2026-12-10", "canal": None},
    {"id": "b", "matricula": "M2", "codLoja": 75, "codMarca": 10, "codCargo": 100, "valorVenda": "20000.00", "dataVenda": "2026-12-11", "canal": None},
]


def registry(vendas=VENDAS, status=200, ultima=True):
    def h(req):
        if status != 200:
            return httpx.Response(status)
        return httpx.Response(200, json={"content": vendas, "last": ultima})

    c = BackendClient(base_url="http://b", timeout=1, transport=httpx.MockTransport(h))
    c.RETRY_BACKOFF_SECONDS = 0
    return criar_registry(c, incluir_simulacao=True)


def bloco(id_, taxa=None, bonus=None, **cond):
    return BlocoProposta(idLocal=id_, condicoes=Condicoes(**cond), taxa=Decimal(taxa) if taxa else None,
                         bonus=bonus, dataInicio=date(2026, 12, 1), dataFim=date(2026, 12, 31))


def llm(*respostas):
    fila = list(respostas)
    p = MagicMock()

    def complete(prompt, response_schema):
        r = fila.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    p.complete.side_effect = complete
    return p


def req(propostas, **kw):
    return SimularRequest(propostas=propostas, competencia="2026-12", **kw)


class TestTemplate(unittest.TestCase):
    def test_cenarios_padrao_e_faixas_com_bonus(self):
        propostas = [
            bloco("p1", "0.02", codLoja=75, faixaValor=FaixaValor(max=Decimal("10000"), maxInclusivo=False)),
            bloco("p2", "0.03", bonus=Bonus(percentual=Decimal("0.01"), valorFixo=Decimal("50")), codLoja=75,
                  faixaValor=FaixaValor(min=Decimal("10000"), minInclusivo=True)),
        ]
        r = ServicoSimulacao(llm(), registry()).simular(req(propostas))
        self.assertEqual(r.origem, "TEMPLATE")
        self.assertEqual(r.simulacao, "SIMULACAO_SANDBOX")
        self.assertIn("Não substitui a apuração", r.aviso)
        self.assertEqual([x.cenario for x in r.resultados], ["Vendas 80%", "Vendas 100%", "Vendas 120%"])
        base = r.resultados[1]
        # a: 1000 -> faixa <10000 -> 2% = 20.00 ; b: 20000 -> 3% = 600 + 1% = 200 + 50 fixo = 850.00
        self.assertEqual(base.porBloco, {"p1": Decimal("20.00"), "p2": Decimal("850.00")})
        self.assertEqual(base.totalComissao, Decimal("870.00"))
        self.assertEqual(base.totalVendas, Decimal("21000.00"))
        self.assertIsNone(r.codigoExecutado)
        self.assertEqual([e.ferramenta for e in r.trilhaFerramentas], ["obter_dados_simulacao", "executar_codigo"])

    def test_cenario_do_pedido(self):
        provider = llm({"cenarios": [{"nome": "Vendas +20%", "multiplicadorVendas": 1.2}], "calculo_adicional": None})
        r = ServicoSimulacao(provider, registry()).simular(req([bloco("p1", "0.02", codLoja=75)], pedido="e se as vendas crescerem 20%?"))
        self.assertEqual(r.origem, "TEMPLATE")
        self.assertEqual(len(r.resultados), 1)
        self.assertEqual(r.resultados[0].totalVendas, Decimal("25200.00"))

    def test_cenarios_dados_nao_chamam_llm(self):
        provider = llm()  # qualquer chamada estoura IndexError
        r = ServicoSimulacao(provider, registry()).simular(req(
            [bloco("p1", "0.02", codLoja=75)], cenarios=[{"nome": "x", "multiplicadorVendas": 1}]))
        self.assertEqual(len(r.resultados), 1)

    def test_proposta_sem_taxa_nao_e_simulada(self):
        r = ServicoSimulacao(llm(), registry()).simular(req([bloco("p1", None, codLoja=75), bloco("p2", "0.02", codLoja=75)]))
        self.assertEqual(list(r.resultados[0].porBloco), ["p2"])
        self.assertTrue(any(p.codigo.value == "CAMPO_AUSENTE" for p in r.pendencias))

    def test_sem_nenhuma_proposta_simulavel(self):
        r = ServicoSimulacao(llm(), registry()).simular(req([bloco("p1", None, codLoja=75)]))
        self.assertEqual(r.resultados, [])

    def test_conflito_nao_calcula_a_venda(self):
        propostas = [bloco("p1", "0.02", codLoja=75), bloco("p2", "0.03", codLoja=75)]
        r = ServicoSimulacao(llm(), registry()).simular(req(propostas))
        self.assertEqual(r.resultados[1].totalComissao, Decimal("0.00"))
        self.assertTrue(any("conflito" in o for o in r.observacoes))

    def test_falha_de_dados_sem_numeros(self):
        r = ServicoSimulacao(llm(), registry(status=503)).simular(req([bloco("p1", "0.02", codLoja=75)]))
        self.assertEqual(r.resultados, [])
        self.assertTrue(any(p.codigo.value == "TOOL_FALHA" for p in r.pendencias))

    def test_sem_vendas(self):
        r = ServicoSimulacao(llm(), registry(vendas=[])).simular(req([bloco("p1", "0.02", codLoja=75)]))
        self.assertEqual(r.resultados, [])
        self.assertTrue(r.pendencias)

    def test_limite_de_cenarios(self):
        cens = [{"nome": f"c{i}", "multiplicadorVendas": 1} for i in range(8)]
        r = ServicoSimulacao(llm(), registry()).simular(req([bloco("p1", "0.02", codLoja=75)], cenarios=cens))
        self.assertEqual(len(r.resultados), 5)
        self.assertTrue(any("Limite" in o for o in r.observacoes))

    def test_llm_falha_ao_extrair_cenarios_usa_padrao(self):
        from app.core.exceptions import LLMProviderError
        provider = llm(LLMProviderError(), LLMProviderError())
        import app.core.llm_retry as lr
        lr.RETRY_BACKOFF_SECONDS = 0
        r = ServicoSimulacao(provider, registry()).simular(req([bloco("p1", "0.02", codLoja=75)], pedido="simule"))
        self.assertEqual(len(r.resultados), 3)

    def test_erro_de_auth_propaga(self):
        with self.assertRaises(LLMAuthenticationError):
            ServicoSimulacao(llm(LLMAuthenticationError()), registry()).simular(
                req([bloco("p1", "0.02", codLoja=75)], pedido="simule"))


CODIGO_RANKING = '''
from decimal import Decimal, ROUND_HALF_UP

def simular(vendas, regras, cenario):
    mult = cenario["multiplicadorVendas"]
    total = Decimal("0")
    por_mat = {}
    for v in vendas:
        val = (v["valorVenda"] * mult).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total += val
        por_mat[v["matricula"]] = por_mat.get(v["matricula"], Decimal("0")) + (val * Decimal("0.01")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    comissao = sum(por_mat.values(), Decimal("0"))
    ranking = sorted(por_mat.items(), key=lambda kv: kv[1], reverse=True)
    return {"cenario": cenario["nome"], "totalVendas": total, "totalComissao": comissao,
            "porBloco": {"p1": comissao}, "porMatricula": por_mat, "ranking": [m for m, _ in ranking]}
'''


class TestCodigoLivre(unittest.TestCase):
    PEDIDO = {"cenarios": [{"nome": "base", "multiplicadorVendas": 1}], "calculo_adicional": "ranking de matrículas por comissão"}

    def test_codigo_livre_validado_devolve_codigo_e_premissas(self):
        provider = llm(self.PEDIDO, {"codigo": CODIGO_RANKING, "premissas": ["1% fixo para todos"]})
        r = ServicoSimulacao(provider, registry()).simular(req([bloco("p1", "0.01", codLoja=75)], pedido="ranking"))
        self.assertEqual(r.origem, "CODIGO_LIVRE")
        self.assertIn("simular(vendas, regras, cenario)", r.codigoExecutado)
        self.assertIn("1% fixo para todos", r.observacoes)
        self.assertEqual(r.resultados[0].totalComissao, Decimal("210.00"))
        # sonda + real + referência do template
        execs = [e for e in r.trilhaFerramentas if e.ferramenta == "executar_codigo"]
        self.assertEqual(len(execs), 3)
        self.assertTrue(all(e.status == "OK" for e in execs))

    def test_codigo_malicioso_bloqueado_sem_numeros(self):
        mal = "import os\ndef simular(vendas, regras, cenario):\n    return {'x': os.environ}\n"
        provider = llm(self.PEDIDO, {"codigo": mal, "premissas": []}, {"codigo": mal, "premissas": []})
        r = ServicoSimulacao(provider, registry()).simular(req([bloco("p1", "0.01", codLoja=75)], pedido="ranking"))
        self.assertEqual(r.resultados, [])
        self.assertTrue(any(p.codigo.value == "SIMULACAO_NAO_VALIDADA" for p in r.pendencias))

    def test_regeneracao_apos_violacao(self):
        mal = "import os\ndef simular(vendas, regras, cenario):\n    return {}\n"
        provider = llm(self.PEDIDO, {"codigo": mal, "premissas": []}, {"codigo": CODIGO_RANKING, "premissas": ["ok"]})
        r = ServicoSimulacao(provider, registry()).simular(req([bloco("p1", "0.01", codLoja=75)], pedido="ranking"))
        self.assertEqual(r.origem, "CODIGO_LIVRE")
        self.assertTrue(r.resultados)

    def test_resultado_incoerente_e_descartado(self):
        incoerente = ("from decimal import Decimal\ndef simular(vendas, regras, cenario):\n"
                      "    return {'cenario': 'x', 'totalVendas': Decimal('100.00'), 'totalComissao': Decimal('10.00'),"
                      " 'porBloco': {'p1': Decimal('3.00')}, 'porMatricula': {'M1': Decimal('10.00')}}\n")
        provider = llm(self.PEDIDO, {"codigo": incoerente, "premissas": []})
        r = ServicoSimulacao(provider, registry()).simular(req([bloco("p1", "0.01", codLoja=75)], pedido="x"))
        self.assertEqual(r.resultados, [])
        self.assertTrue(any("soma" in p.mensagem for p in r.pendencias))

    def test_total_de_vendas_divergente_do_template(self):
        errado = CODIGO_RANKING.replace('total += val', 'total += val + Decimal("1")')
        provider = llm(self.PEDIDO, {"codigo": errado, "premissas": []})
        r = ServicoSimulacao(provider, registry()).simular(req([bloco("p1", "0.01", codLoja=75)], pedido="x"))
        self.assertEqual(r.resultados, [])
        self.assertTrue(any("diverge" in p.mensagem for p in r.pendencias))

    def test_limite_de_execucoes(self):
        provider = llm(self.PEDIDO, {"codigo": CODIGO_RANKING, "premissas": []})
        r = ServicoSimulacao(provider, registry(), limites=Limites(max_code_executions=0)).simular(
            req([bloco("p1", "0.01", codLoja=75)], pedido="x"))
        self.assertEqual(r.resultados, [])
        self.assertTrue(any(p.codigo.value == "LIMITE_AGENTE_ATINGIDO" for p in r.pendencias))

    def test_pedido_simples_nao_usa_codigo_livre(self):
        provider = llm({"cenarios": [], "calculo_adicional": None})
        r = ServicoSimulacao(provider, registry()).simular(req([bloco("p1", "0.01", codLoja=75)], pedido="simule"))
        self.assertEqual(r.origem, "TEMPLATE")
        self.assertEqual(provider.complete.call_count, 1)  # só a extração de cenários


class TestRotaSimular(unittest.TestCase):
    def tearDown(self):
        app.dependency_overrides.clear()

    def test_rota(self):
        app.dependency_overrides[get_simulador] = lambda: ServicoSimulacao(llm(), registry())
        corpo = {"competencia": "2026-12", "propostas": [{"idLocal": "p1", "taxa": "0.02", "condicoes": {"codLoja": 75}}]}
        r = TestClient(app).post("/api/v2/simular", json=corpo)
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertEqual(j["simulacao"], "SIMULACAO_SANDBOX")
        self.assertEqual(j["origem"], "TEMPLATE")
        self.assertEqual(len(j["resultados"]), 3)

    def test_competencia_invalida(self):
        r = TestClient(app).post("/api/v2/simular", json={"competencia": "dez/2026", "propostas": []})
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()
