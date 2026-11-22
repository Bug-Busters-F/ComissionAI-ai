"""
Testes de contrato do IA-10 (BUG-123): chave interna de entrada, X-Correlation-Id, catálogo de erros,
rastreabilidade dos identificadores e compatibilidade com o payload do backend (BACK-10).
"""

import logging
import os
import sys
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts")))
sys.path.insert(0, os.path.dirname(__file__))

from app.api.routes.v2 import get_simulador  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.erros import CATALOGO  # noqa: E402
from app.core.simulacao.servico import ServicoSimulacao  # noqa: E402
from app.main import app  # noqa: E402
from exportar_contratos import DESTINO, schemas  # noqa: E402
from test_cenarios_orcamento import registry_sem_chamadas, sem_llm  # noqa: E402

ANOMALIAS = "/api/v2/anomalias/analisar"
CORPO_ANOMALIAS = {"competencia": "2025-11", "vendas": []}

# ---------------------------------------------------------------- payload no formato do backend (BACK-10)
CONTEXTO = {"campanhaId": "42", "revisao": 3, "execucaoId": "exec-9f1", "usuarioSolicitanteId": "user-7",
            "versaoPrograma": "prog-v2"}
VERSOES_FONTES = {
    "hashRecorte": "a" * 64, "hashVendas": "b" * 64, "hashRh": "c" * 64, "hashTaxasContratuais": "d" * 64,
    "hashRegras": "e" * 64, "hashPendenciasAceitas": None,
    "campanha": {"campanhaId": 42, "titulo": "Natal", "estado": "RASCUNHO", "versaoId": 7, "versaoNumero": 3,
                 "statusVersao": "EM_REVISAO", "hashArtefatosCodigo": "f" * 64, "orcamento": 40},
    "resumoVendas": {"totalRegistros": 3, "versaoMinima": 1, "versaoMaxima": 1, "totalRegistrosEditados": 0,
                     "lotesOrigemDistintos": ["L1"], "lotesAlteracaoDistintos": []},
    "lotesFontes": [{"idLote": "L1", "tipoBase": "VENDAS", "competencia": "2025-11", "hashConteudo": "9" * 64,
                     "anexadoACampanha": True}],
}


def venda_dto(i, valor, loja=75):
    """Todos os campos de VendaRecorteIaDTO (os extras são ignorados pela IA)."""
    return {"id": f"00000000-0000-0000-0000-00000000000{i}", "matricula": f"MATRIC-{i}", "codLoja": loja,
            "descrLoja": f"LOJA-{loja}", "codMarca": 10, "descrMarca": "PRETO", "codCargo": 100,
            "descriCargo": "VENDEDOR LOJA", "valorVenda": valor, "dataVenda": "2025-11-24", "competencia": "2025-11",
            "canal": None, "tipoVenda": "LOJA", "idLoteOrigem": "L1", "versao": 1,
            "origemUltimaAlteracao": "IMPORTACAO", "idLoteUltimaAlteracao": "L1",
            "atualizadoEm": "2025-11-30T10:00:00-03:00"}


TAXA_DTO = {"id": "10000000-0000-0000-0000-000000000001", "codMarca": 10, "descrMarca": "PRETO", "codCargo": 100,
            "descriCargo": "VENDEDOR LOJA", "competencia": "2025-11", "mesReferencia": "2025-11-01", "taxa": 0.025,
            "idLoteOrigem": "T1", "percentual": 0.025}
PENDENCIA_DTO = {"inconsistenciaId": 5, "reportId": 2, "idLote": "L1", "tipoBase": "VENDAS", "competencia": "2025-11",
                 "linha": 12, "campo": "Vlr_Venda", "motivo": "valor fora do padrão", "severidade": "AVISO",
                 "aceitaPor": "user-7", "aceitaEm": "2025-12-01T09:00:00-03:00", "motivoAceite": "conferido"}
RH_DTO = {"id": "20000000-0000-0000-0000-000000000001", "matricula": "MATRIC-1", "codLoja": 75, "descrLoja": "LOJA-75",
          "codCargo": 100, "descriCargo": "VENDEDOR LOJA", "dataAdmissao": "2020-01-01", "dataDemissao": None,
          "idLoteOrigem": "R1", "versao": 1}

SIMULAR_BACKEND = {
    "contexto": CONTEXTO,
    "competencia": "2025-11",
    "propostas": [{"idLocal": "p1", "taxa": "0.05", "condicoes": {"codLoja": 75,
                                                                  "faixaValor": {"min": 1000, "minInclusivo": True}}}],
    "cenarios": [],
    "vendas": [venda_dto(1, 1000.00), venda_dto(2, 500.00), venda_dto(3, 800.00, loja=99)],
    "taxasContratuais": [TAXA_DTO],
    "pendenciasAceitas": [PENDENCIA_DTO],
    "versoesFontes": VERSOES_FONTES,
    "orcamento": 35,
    "periodoCampanha": {"dataInicio": "2026-12-01", "dataFim": "2026-12-15"},
    "calibrar": True,
}


class Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()


class TestChaveInterna(Base):
    def test_sem_chave_configurada_rotas_abertas_em_desenvolvimento(self):
        with patch.object(settings, "ai_service_api_key", ""):
            self.assertEqual(self.client.post(ANOMALIAS, json=CORPO_ANOMALIAS).status_code, 200)

    def test_chave_ausente_ou_errada(self):
        with patch.object(settings, "ai_service_api_key", "segredo-123"):
            for headers in ({}, {"X-Internal-Api-Key": "errada"}, {"X-Internal-Api-Key": ""}):
                r = self.client.post(ANOMALIAS, json=CORPO_ANOMALIAS, headers=headers)
                self.assertEqual(r.status_code, 401)
                self.assertEqual(r.json()["error_code"], "CHAVE_INTERNA_INVALIDA")
                self.assertIn("X-Correlation-Id", r.headers)

    def test_chave_correta_e_header_configuravel(self):
        with patch.object(settings, "ai_service_api_key", "segredo-123"):
            ok = self.client.post(ANOMALIAS, json=CORPO_ANOMALIAS, headers={"X-Internal-Api-Key": "segredo-123"})
            self.assertEqual(ok.status_code, 200)
            with patch.object(settings, "ai_service_auth_header", "X-Outra-Chave"):
                r = self.client.post(ANOMALIAS, json=CORPO_ANOMALIAS, headers={"X-Outra-Chave": "segredo-123"})
                self.assertEqual(r.status_code, 200)

    def test_health_e_documentacao_livres(self):
        with patch.object(settings, "ai_service_api_key", "segredo-123"):
            self.assertEqual(self.client.get("/health").status_code, 200)
            self.assertEqual(self.client.get("/openapi.json").status_code, 200)

    def test_obrigatoria_sem_chave_recusa(self):
        with patch.object(settings, "ai_service_api_key", ""), \
                patch.object(settings, "ai_inbound_auth_obrigatoria", True):
            r = self.client.post(ANOMALIAS, json=CORPO_ANOMALIAS)
            self.assertEqual((r.status_code, r.json()["error_code"]), (503, "AUTH_NAO_CONFIGURADA"))
            self.assertEqual(self.client.get("/health").status_code, 200)

    def test_chave_nunca_vai_para_o_log(self):
        with patch.object(settings, "ai_service_api_key", "segredo-123"), \
                self.assertLogs(level=logging.INFO) as logs:
            self.client.post(ANOMALIAS, json=CORPO_ANOMALIAS, headers={"X-Internal-Api-Key": "segredo-123"})
            self.client.post(ANOMALIAS, json=CORPO_ANOMALIAS, headers={"X-Internal-Api-Key": "segredo-errado"})
        self.assertFalse(any("segredo" in linha for linha in logs.output))


class TestCorrelacao(Base):
    def test_devolve_o_id_recebido(self):
        r = self.client.post(ANOMALIAS, json=CORPO_ANOMALIAS, headers={"X-Correlation-Id": "back-req-1"})
        self.assertEqual(r.headers["X-Correlation-Id"], "back-req-1")

    def test_gera_quando_ausente_ou_invalido(self):
        for headers in ({}, {"X-Correlation-Id": "com espaco"}, {"X-Correlation-Id": "x" * 200}):
            gerado = self.client.get("/health", headers=headers).headers["X-Correlation-Id"]
            self.assertRegex(gerado, r"^[0-9a-f]{32}$")

    def test_correlacao_nos_logs_da_requisicao(self):
        from app.api.middleware import FiltroCorrelacao

        class Coletor(logging.Handler):
            def __init__(self):
                super().__init__()
                self.ids = []

            def emit(self, record):
                self.ids.append(record.correlation_id)

        coletor = Coletor()
        coletor.addFilter(FiltroCorrelacao())
        log = logging.getLogger("app.acesso")
        log.addHandler(coletor)
        nivel = log.level
        log.setLevel(logging.INFO)
        try:
            self.client.post(ANOMALIAS, json=CORPO_ANOMALIAS, headers={"X-Correlation-Id": "corr-77"})
        finally:
            log.removeHandler(coletor)
            log.setLevel(nivel)
        self.assertEqual(coletor.ids, ["corr-77"])


class TestCatalogoErros(Base):
    def test_validacao(self):
        r = self.client.post(ANOMALIAS, json={"competencia": "11/2025", "vendas": []})
        corpo = r.json()
        self.assertEqual((r.status_code, corpo["error_code"]), (422, "VALIDACAO_ENTRADA"))
        self.assertEqual(corpo["erros"][0]["loc"], ["body", "competencia"])
        self.assertIsInstance(corpo["detail"], str)

    def test_nao_encontrado(self):
        r = self.client.get("/api/v2/programa/" + "0" * 64)
        self.assertEqual((r.status_code, r.json()["error_code"]), (404, "NAO_ENCONTRADO"))
        self.assertEqual(r.json()["detail"], "Nenhum programa encontrado para essa assinatura.")
        self.assertEqual(self.client.get("/rota-inexistente").json()["error_code"], "NAO_ENCONTRADO")

    def test_volume(self):
        with patch.object(settings, "anomalia_max_vendas", 1):
            corpo = {"competencia": "2025-11", "vendas": [venda_dto(1, 10), venda_dto(2, 20)]}
            r = self.client.post(ANOMALIAS, json=corpo)
        self.assertEqual((r.status_code, r.json()["error_code"]), (413, "VOLUME_EXCEDIDO"))

    def test_todo_codigo_tem_status_e_acao(self):
        for codigo, e in CATALOGO.items():
            self.assertTrue(400 <= e.status < 600 and e.mensagem and e.acao_backend, codigo)


class TestPayloadDoBackend(Base):
    """O payload no formato exato dos DTOs Java é aceito e os identificadores voltam na resposta."""

    @classmethod
    def setUpClass(cls):
        app.dependency_overrides[get_simulador] = lambda: ServicoSimulacao(sem_llm(), registry_sem_chamadas())
        cliente = TestClient(app)
        cls.sim = cliente.post("/api/v2/simular", json=SIMULAR_BACKEND, headers={"X-Correlation-Id": "c-1"})
        app.dependency_overrides.clear()
        cls.anom = cliente.post(ANOMALIAS, json={
            "contexto": CONTEXTO, "competencia": "2025-11", "versoesFontes": VERSOES_FONTES,
            "vendas": [venda_dto(i, 1000 + i * 10) for i in range(1, 10)], "dadosRh": [RH_DTO]})

    def test_simular_aceita_o_recorte(self):
        self.assertEqual(self.sim.status_code, 200, self.sim.text)
        corpo = self.sim.json()
        self.assertEqual(len(corpo["resultados"]), 4)
        self.assertEqual(corpo["statusSugestoes"], "OK")
        self.assertEqual(self.sim.headers["X-Correlation-Id"], "c-1")

    def test_identificadores_propagados(self):
        corpo = self.sim.json()
        self.assertEqual(corpo["contexto"], {**CONTEXTO, "origem": "NOVA", "substituiVersao": None})
        self.assertTrue(all(e["execucaoId"] == "exec-9f1" for e in corpo["explicacoes"]))
        self.assertTrue(all(c["assinaturaPrograma"] == corpo["assinaturaPrograma"] for c in corpo["calibracoes"]))

    def test_hashes_do_recorte_em_versao_fontes(self):
        recorte = self.sim.json()["versaoFontes"]["recorte"]
        self.assertEqual(recorte["hashRecorte"], "a" * 64)
        self.assertEqual(recorte["campanha.versaoNumero"], 3)
        self.assertNotIn("hashPendenciasAceitas", recorte)  # nulo não é inventado
        self.assertNotIn("lotesFontes", recorte)

    def test_pendencias_aceitas_viram_riscos(self):
        self.assertEqual(len(self.sim.json()["riscos"]), 1)

    def test_anomalias_aceitam_o_recorte(self):
        self.assertEqual(self.anom.status_code, 200, self.anom.text)
        corpo = self.anom.json()
        self.assertEqual(corpo["versaoFontes"]["hashRecorte"], "a" * 64)
        self.assertEqual(corpo["contexto"]["usuarioSolicitanteId"], "user-7")
        # dadosRh informado é a referência: só MATRIC-1 existe no RH
        self.assertEqual(corpo["resumo"]["vendasComErroCarga"], 8)


class TestSchemasExportados(unittest.TestCase):
    def test_contratos_exportados_estao_atualizados(self):
        for nome, conteudo in schemas().items():
            arquivo = DESTINO / nome
            self.assertTrue(arquivo.exists(), f"{nome} ausente: rode scripts/exportar_contratos.py")
            self.assertEqual(arquivo.read_text(encoding="utf-8"), conteudo,
                             f"{nome} desatualizado: rode scripts/exportar_contratos.py e revise a mudança")


if __name__ == "__main__":
    unittest.main()
