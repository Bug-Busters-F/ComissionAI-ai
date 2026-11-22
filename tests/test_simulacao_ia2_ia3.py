"""
Testes de IA-2 (gerar-programa, versão identificável, sem reinventar código ao simular) e
IA-3 (recorte de vendas do backend como fonte única de dados) — Sprint 3.
"""

import hashlib
import os
import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import httpx
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from app.api.routes.v2 import get_simulador
from app.core.config import settings
from app.core.exceptions import LLMRateLimitError
from app.core.simulacao.servico import ServicoSimulacao
from app.core.simulacao.templates import TEMPLATE_CODIGO
from app.main import app
from app.schemas.proposta import BlocoProposta, Condicoes, GerarProgramaRequest, SimularRequest
from app.tools import BackendClient, criar_registry

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
    return {"cenario": cenario["nome"], "totalVendas": total, "totalComissao": comissao,
            "porBloco": {"p1": comissao}, "porMatricula": por_mat}
'''


def bloco(id_, taxa):
    return BlocoProposta(idLocal=id_, condicoes=Condicoes(codLoja=75), taxa=Decimal(taxa),
                         dataInicio=date(2026, 12, 1), dataFim=date(2026, 12, 31))


def llm(*respostas):
    fila = list(respostas)
    p = MagicMock()

    def complete(prompt, response_schema):
        item = fila.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    p.complete.side_effect = complete
    return p


def registry_sem_chamadas():
    """Backend que FALHA se for chamado — prova de que o recorte não disparou nenhuma consulta por fora."""
    def h(req: httpx.Request):
        raise AssertionError(f"Consulta inesperada ao backend: {req.url.path}")

    c = BackendClient(base_url="http://b", timeout=1, transport=httpx.MockTransport(h))
    c.RETRY_BACKOFF_SECONDS = 0
    return criar_registry(c, incluir_simulacao=True)


class TestGerarPrograma(unittest.TestCase):
    def test_sem_calculo_adicional_devolve_template_sem_codigo(self):
        provider = llm({"cenarios": [], "calculo_adicional": None})
        r = ServicoSimulacao(provider, registry_sem_chamadas()).gerar_programa(
            GerarProgramaRequest(propostas=[bloco("p1", "0.02")]))
        self.assertEqual(r.origem, "TEMPLATE")
        self.assertIsNone(r.codigo)
        self.assertEqual(r.assinatura, hashlib.sha256(TEMPLATE_CODIGO.encode()).hexdigest())
        self.assertEqual(r.pendencias, [])

    def test_com_calculo_adicional_gera_e_valida_devolvendo_assinatura(self):
        provider = llm(
            {"cenarios": [], "calculo_adicional": "ranking de matrículas"},
            {"codigo": CODIGO_RANKING, "premissas": ["1% fixo"]},
        )
        r = ServicoSimulacao(provider, registry_sem_chamadas()).gerar_programa(
            GerarProgramaRequest(propostas=[bloco("p1", "0.02")], pedido="ranking"))
        self.assertEqual(r.origem, "CODIGO_LIVRE")
        self.assertEqual(r.codigo, CODIGO_RANKING)
        self.assertEqual(r.assinatura, hashlib.sha256(CODIGO_RANKING.encode()).hexdigest())
        self.assertEqual(r.premissas, ["1% fixo"])

    def test_falha_de_extracao_nao_vira_decisao_silenciosa_de_template(self):
        """Achado testando com LLM real: rate limit na extração caía pro TEMPLATE sem avisar,
        indistinguível de "o pedido realmente não precisa de cálculo extra"."""
        provider = llm(LLMRateLimitError())
        r = ServicoSimulacao(provider, registry_sem_chamadas()).gerar_programa(
            GerarProgramaRequest(propostas=[bloco("p1", "0.02")], pedido="algo"))
        self.assertEqual(r.origem, "TEMPLATE")
        self.assertTrue(any(p.codigo.value == "TOOL_FALHA" for p in r.pendencias))

    def test_codigo_malicioso_nao_e_aprovado(self):
        mal = "import os\ndef simular(vendas, regras, cenario):\n    return {'x': os.environ}\n"
        provider = llm({"cenarios": [], "calculo_adicional": "x"}, {"codigo": mal, "premissas": []},
                       {"codigo": mal, "premissas": []})
        r = ServicoSimulacao(provider, registry_sem_chamadas()).gerar_programa(
            GerarProgramaRequest(propostas=[bloco("p1", "0.02")], pedido="x"))
        self.assertTrue(any(p.codigo.value == "SIMULACAO_NAO_VALIDADA" for p in r.pendencias))
        self.assertEqual(r.codigo, None)


class TestSimularComCodigoAprovado(unittest.TestCase):
    """IA-2: /simular não deve reinventar o código quando já veio aprovado de /gerar-programa."""

    def test_executa_sem_regerar_quando_codigo_aprovado_e_assinatura_batem(self):
        assinatura = hashlib.sha256(CODIGO_RANKING.encode()).hexdigest()
        provider = llm()  # nenhuma chamada ao LLM deveria acontecer neste caminho
        req = SimularRequest(
            propostas=[bloco("p1", "0.02")], competencia="2026-12",
            vendas=[{"id": "v1", "matricula": "M1", "codLoja": 75, "codMarca": 10, "codCargo": 100,
                    "valorVenda": "1000.00", "dataVenda": "2026-12-10", "canal": None}],
            codigoAprovado=CODIGO_RANKING, assinaturaPrograma=assinatura,
        )
        r = ServicoSimulacao(provider, registry_sem_chamadas()).simular(req)
        self.assertEqual(r.origem, "CODIGO_LIVRE")
        self.assertEqual(r.assinaturaPrograma, assinatura)
        self.assertEqual(r.versaoFontes["origemDados"], "RECORTE_BACKEND")
        self.assertEqual(r.versaoFontes["qtdVendas"], 1)
        provider.complete.assert_not_called()
        self.assertTrue(any("não foi reinterpretado" in o for o in r.observacoes))

    def test_assinatura_divergente_bloqueia_execucao(self):
        req = SimularRequest(
            propostas=[bloco("p1", "0.02")], competencia="2026-12",
            vendas=[{"id": "v1", "matricula": "M1", "codLoja": 75, "codMarca": 10, "codCargo": 100,
                    "valorVenda": "1000.00", "dataVenda": "2026-12-10", "canal": None}],
            codigoAprovado=CODIGO_RANKING, assinaturaPrograma="assinatura-errada",
        )
        r = ServicoSimulacao(llm(), registry_sem_chamadas()).simular(req)
        self.assertEqual(r.resultados, [])
        self.assertTrue(any("assinatura" in p.mensagem.lower() for p in r.pendencias))


class TestRecorteDoBackend(unittest.TestCase):
    """IA-3: vendas enviadas no corpo são a ÚNICA fonte; não há busca silenciosa a outra base."""

    def test_recorte_e_usado_sem_chamar_a_consulta_interna(self):
        req = SimularRequest(
            propostas=[bloco("p1", "0.02")], competencia="2026-12",
            vendas=[
                {"id": "v1", "matricula": "M1", "codLoja": 75, "codMarca": 10, "codCargo": 100,
                 "valorVenda": "1000.00", "dataVenda": "2026-12-10", "canal": None},
                {"id": "v2", "matricula": "M2", "codLoja": 75, "codMarca": 10, "codCargo": 100,
                 "valorVenda": "500.00", "dataVenda": "2026-12-11", "canal": None},
            ],
        )
        r = ServicoSimulacao(llm({"cenarios": [], "calculo_adicional": None}), registry_sem_chamadas()).simular(req)
        self.assertEqual(r.origem, "TEMPLATE")
        self.assertEqual(r.versaoFontes, {"origemDados": "RECORTE_BACKEND", "competencia": "2026-12", "qtdVendas": 2})
        # cenário padrão "100%" (índice 1 de 80/100/120) preserva o total do recorte
        self.assertEqual(r.resultados[1].totalVendas, Decimal("1500.00"))

    def test_recorte_vazio_nao_cai_para_consulta_interna(self):
        """Recorte vazio é uma falha explícita, não um motivo pra ir buscar dados em outro lugar."""
        req = SimularRequest(propostas=[bloco("p1", "0.02")], competencia="2026-12", vendas=[])
        r = ServicoSimulacao(llm({"cenarios": [], "calculo_adicional": None}), registry_sem_chamadas()).simular(req)
        self.assertEqual(r.resultados, [])
        self.assertTrue(any("recorte" in p.mensagem.lower() for p in r.pendencias))


class TestBuscarPrograma(unittest.TestCase):
    """GET /api/v2/programa/{assinatura}: código recuperável pra revisão posterior (IA-2)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._dir_original = settings.sim_dir_programas
        settings.sim_dir_programas = self._tmp.name

    def tearDown(self):
        settings.sim_dir_programas = self._dir_original
        self._tmp.cleanup()

    def test_template_e_sempre_recuperavel_sem_ter_sido_gerado(self):
        servico = ServicoSimulacao(llm(), registry_sem_chamadas())
        assinatura = hashlib.sha256(TEMPLATE_CODIGO.encode()).hexdigest()
        programa = servico.buscar_programa(assinatura)
        self.assertIsNotNone(programa)
        self.assertEqual(programa.codigo, TEMPLATE_CODIGO)

    def test_assinatura_desconhecida_devolve_none(self):
        servico = ServicoSimulacao(llm(), registry_sem_chamadas())
        self.assertIsNone(servico.buscar_programa("0" * 64))

    def test_assinatura_mal_formada_devolve_none_em_vez_de_lancar(self):
        """Bug achado em review: caractere fora de [0-9a-f] fazia _arquivo() lançar ValueError
        sem ninguém capturar, virando 500 na rota em vez de 'não encontrado'."""
        servico = ServicoSimulacao(llm(), registry_sem_chamadas())
        self.assertIsNone(servico.buscar_programa("abc-nao-hex!!"))

    def test_rota_get_404_para_assinatura_mal_formada(self):
        app.dependency_overrides[get_simulador] = lambda: ServicoSimulacao(llm(), registry_sem_chamadas())
        r = TestClient(app).get("/api/v2/programa/abc-nao-hex!!")
        self.assertEqual(r.status_code, 404)
        app.dependency_overrides.clear()

    def test_codigo_livre_gerado_fica_disponivel_para_busca_posterior(self):
        provider = llm(
            {"cenarios": [], "calculo_adicional": "ranking de matrículas"},
            {"codigo": CODIGO_RANKING, "premissas": ["1% fixo"]},
        )
        servico = ServicoSimulacao(provider, registry_sem_chamadas())
        gerado = servico.gerar_programa(GerarProgramaRequest(propostas=[bloco("p1", "0.02")], pedido="ranking"))

        recuperado = servico.buscar_programa(gerado.assinatura)
        self.assertIsNotNone(recuperado)
        self.assertEqual(recuperado.codigo, CODIGO_RANKING)
        self.assertEqual(recuperado.premissas, ["1% fixo"])

    def test_rota_get_404_para_assinatura_inexistente(self):
        app.dependency_overrides[get_simulador] = lambda: ServicoSimulacao(llm(), registry_sem_chamadas())
        r = TestClient(app).get(f"/api/v2/programa/{'0' * 64}")
        self.assertEqual(r.status_code, 404)
        app.dependency_overrides.clear()

    def test_premissas_nao_se_perdem_ao_reusar_codigo_aprovado(self):
        """Bug achado em review: _caminho_aprovado passava premissas=[] fixo pra
        _executar_codigo_aprovado, mesmo elas estando recuperáveis via buscar_programa."""
        provider = llm(
            {"cenarios": [], "calculo_adicional": "ranking de matrículas"},
            {"codigo": CODIGO_RANKING, "premissas": ["1% fixo sobre o excedente da meta"]},
        )
        servico = ServicoSimulacao(provider, registry_sem_chamadas())
        gerado = servico.gerar_programa(GerarProgramaRequest(propostas=[bloco("p1", "0.02")], pedido="ranking"))

        req = SimularRequest(
            propostas=[bloco("p1", "0.02")], competencia="2026-12",
            vendas=[{"id": "v1", "matricula": "M1", "codLoja": 75, "codMarca": 10, "codCargo": 100,
                    "valorVenda": "1000.00", "dataVenda": "2026-12-10", "canal": None}],
            codigoAprovado=gerado.codigo, assinaturaPrograma=gerado.assinatura,
        )
        r = servico.simular(req)
        self.assertIn("1% fixo sobre o excedente da meta", r.observacoes)

    def test_rota_get_200_apos_gerar_programa(self):
        provider = llm(
            {"cenarios": [], "calculo_adicional": "ranking de matrículas"},
            {"codigo": CODIGO_RANKING, "premissas": ["1% fixo"]},
        )
        app.dependency_overrides[get_simulador] = lambda: ServicoSimulacao(provider, registry_sem_chamadas())
        cliente = TestClient(app)
        corpo = {"propostas": [{"idLocal": "p1", "taxa": "0.02", "condicoes": {"codLoja": 75}}], "pedido": "ranking"}
        gerado = cliente.post("/api/v2/gerar-programa", json=corpo).json()

        r = cliente.get(f"/api/v2/programa/{gerado['assinatura']}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["codigo"], CODIGO_RANKING)
        app.dependency_overrides.clear()


class TestRotaGerarPrograma(unittest.TestCase):
    def tearDown(self):
        app.dependency_overrides.clear()

    def test_rota(self):
        app.dependency_overrides[get_simulador] = lambda: ServicoSimulacao(
            llm({"cenarios": [], "calculo_adicional": None}), registry_sem_chamadas())
        corpo = {"propostas": [{"idLocal": "p1", "taxa": "0.02", "condicoes": {"codLoja": 75}}]}
        r = TestClient(app).post("/api/v2/gerar-programa", json=corpo)
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertEqual(j["origem"], "TEMPLATE")
        self.assertIsNone(j["codigo"])
        self.assertTrue(j["assinatura"])


if __name__ == "__main__":
    unittest.main()
