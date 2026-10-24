"""
Testes de auditoria de falhas, ausências e integração do agente para IA-9 (BUG-81).
Garante conformidade com o CONTRATO-INTERPRETAR-V2 e Jira BUG-81.
"""

import os
import sys
import unittest
from decimal import Decimal
from unittest.mock import MagicMock

import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from app.core.agente import AgenteInterpretador
from app.core.agente.hooks import HooksAjusteSobreBase
from app.core.exceptions import LLMTimeoutError
from app.schemas.proposta import CodigoPendencia, ContextoProposta, InterpretarRequestV2
from app.tools import BackendClient, criar_registry
from app.tools.client import BackendErro


class TestIA9FalhasEIntegracao(unittest.TestCase):
    """Testes de tratamento de falhas e ausências no agente."""

    def test_distincao_sem_dados_vs_falha_em_client(self):
        """BackendClient não deve retentar 4xx (erro de negócio), mas retenta 5xx (falha transitória)."""
        tentativas_503 = 0
        def h_503(req: httpx.Request):
            nonlocal tentativas_503
            tentativas_503 += 1
            return httpx.Response(503, text="Service Unavailable")

        client_503 = BackendClient(base_url="http://mock", timeout=1, transport=httpx.MockTransport(h_503))
        client_503.RETRY_BACKOFF_SECONDS = 0
        with self.assertRaises(BackendErro) as ctx:
            client_503.get("/bases")
        self.assertEqual(ctx.exception.tipo, "HTTP_503")
        self.assertEqual(tentativas_503, 2)  # Fez 1 retry

        tentativas_404 = 0
        def h_404(req: httpx.Request):
            nonlocal tentativas_404
            tentativas_404 += 1
            return httpx.Response(404, text="Not Found")

        client_404 = BackendClient(base_url="http://mock", timeout=1, transport=httpx.MockTransport(h_404))
        client_404.RETRY_BACKOFF_SECONDS = 0
        with self.assertRaises(BackendErro) as ctx:
            client_404.get("/bases")
        self.assertEqual(ctx.exception.tipo, "HTTP_404")
        self.assertEqual(tentativas_404, 1)  # 4xx não retenta

    def test_503_em_bases_gera_tool_falha_nao_base_ausente(self):
        """Falha 503 na consulta de base deve gerar TOOL_FALHA, nunca BASE_AUSENTE."""
        extracao = {
            "regras": [
                {
                    "trecho_origem": "mais 1 pp para gerentes da marca 10 em dezembro",
                    "operacao_raw": "mais 1 pp",
                    "cargo_raw": "gerentes",
                    "marca_raw": "10",
                }
            ],
            "vigencia_inicio_raw": "2026-12-01",
            "vigencia_fim_raw": "2026-12-31",
        }

        def h(req: httpx.Request):
            p = req.url.path
            if p.endswith("/cargos"):
                return httpx.Response(200, json={"encontrado": True, "itens": [{"codigo": 150, "descricao": "GERENTE"}]})
            if p.endswith("/marcas"):
                return httpx.Response(200, json={"encontrado": True, "itens": [{"codigo": 10, "descricao": "MARCA 10"}]})
            if p.endswith("/bases"):
                return httpx.Response(503, text="Service Unavailable")
            if p.endswith("/regras-concorrentes"):
                return httpx.Response(200, json={"conflitos": []})
            return httpx.Response(404)

        client = BackendClient(base_url="http://mock", timeout=1, transport=httpx.MockTransport(h))
        client.RETRY_BACKOFF_SECONDS = 0
        registry = criar_registry(client=client)

        provider = MagicMock()
        provider.complete.return_value = extracao

        agente = AgenteInterpretador(provider, registry, hooks=HooksAjusteSobreBase())

        req = InterpretarRequestV2(
            texto="mais 1 pp para gerentes da marca 10 em dezembro",
            competencia="2026-12",
        )

        res = agente.executar(req)
        self.assertEqual(len(res.propostas), 1)
        p = res.propostas[0]
        self.assertIsNone(p.taxa)
        # Deve ter TOOL_FALHA e NÃO BASE_AUSENTE
        self.assertTrue(any(pend.codigo == CodigoPendencia.TOOL_FALHA for pend in p.pendencias))
        self.assertFalse(any(pend.codigo == CodigoPendencia.BASE_AUSENTE for pend in p.pendencias))

    def test_base_ausente_nao_inventa_percentual(self):
        """Base ausente (SEM_DADOS) deve registrar BASE_AUSENTE e taxa=null, sem estimar valor."""
        extracao = {
            "regras": [
                {
                    "trecho_origem": "mais 1 pp para vendedores da marca 10",
                    "operacao_raw": "mais 1 pp",
                    "cargo_raw": "vendedores",
                    "marca_raw": "10",
                }
            ],
            "vigencia_inicio_raw": "2026-12-01",
            "vigencia_fim_raw": "2026-12-31",
        }

        def h(req: httpx.Request):
            p = req.url.path
            if p.endswith("/cargos"):
                return httpx.Response(200, json={"encontrado": True, "itens": [{"codigo": 100, "descricao": "VENDEDOR"}]})
            if p.endswith("/marcas"):
                return httpx.Response(200, json={"encontrado": True, "itens": [{"codigo": 10, "descricao": "MARCA 10"}]})
            if p.endswith("/bases"):
                return httpx.Response(200, json={"encontrado": False})
            return httpx.Response(404)

        client = BackendClient(base_url="http://mock", timeout=1, transport=httpx.MockTransport(h))
        registry = criar_registry(client=client)

        provider = MagicMock()
        provider.complete.return_value = extracao

        agente = AgenteInterpretador(provider, registry, hooks=HooksAjusteSobreBase())
        res = agente.executar(InterpretarRequestV2(texto="mais 1 pp para vendedores da marca 10", competencia="2026-12"))

        p = res.propostas[0]
        self.assertIsNone(p.taxa)
        self.assertTrue(any(pend.codigo == CodigoPendencia.BASE_AUSENTE for pend in p.pendencias))

    def test_consulta_ambigua_nao_escolhe_cargo(self):
        """Consulta ambígua em cargos não pode escolher nenhum cargo automaticamente."""
        extracao = {
            "regras": [
                {
                    "trecho_origem": "3% para assistentes",
                    "taxa_raw": "3%",
                    "cargo_raw": "assistentes",
                }
            ],
            "vigencia_inicio_raw": "2026-12-01",
            "vigencia_fim_raw": "2026-12-31",
        }

        def h(req: httpx.Request):
            p = req.url.path
            if p.endswith("/cargos"):
                return httpx.Response(200, json={
                    "encontrado": True,
                    "itens": [
                        {"codigo": 110, "descricao": "ASSISTENTE COMERCIAL"},
                        {"codigo": 111, "descricao": "ASSISTENTE ADMINISTRATIVO"},
                    ]
                })
            return httpx.Response(404)

        client = BackendClient(base_url="http://mock", timeout=1, transport=httpx.MockTransport(h))
        registry = criar_registry(client=client)

        provider = MagicMock()
        provider.complete.return_value = extracao

        agente = AgenteInterpretador(provider, registry, hooks=HooksAjusteSobreBase())
        res = agente.executar(InterpretarRequestV2(texto="3% para assistentes em dezembro", competencia="2026-12"))

        p = res.propostas[0]
        # Não escolheu nenhum cargo
        self.assertIsNone(p.condicoes.codCargo)
        self.assertIsNone(p.condicoes.descriCargo)
        self.assertTrue(any(pend.codigo == CodigoPendencia.AMBIGUIDADE_CARGO for pend in p.pendencias))

    def test_sem_dados_em_resolve_publico_gera_cadastro_inexistente(self):
        """Quando cargo não existe, gera CADASTRO_INEXISTENTE e codCargo fica None."""
        extracao = {
            "regras": [
                {
                    "trecho_origem": "3% para astronautas",
                    "taxa_raw": "3%",
                    "cargo_raw": "astronautas",
                }
            ],
            "vigencia_inicio_raw": "2026-12-01",
            "vigencia_fim_raw": "2026-12-31",
        }

        def h(req: httpx.Request):
            p = req.url.path
            if p.endswith("/cargos"):
                return httpx.Response(200, json={"encontrado": False, "itens": []})
            return httpx.Response(404)

        client = BackendClient(base_url="http://mock", timeout=1, transport=httpx.MockTransport(h))
        registry = criar_registry(client=client)

        provider = MagicMock()
        provider.complete.return_value = extracao

        agente = AgenteInterpretador(provider, registry, hooks=HooksAjusteSobreBase())
        res = agente.executar(InterpretarRequestV2(texto="3% para astronautas em dezembro"))

        p = res.propostas[0]
        self.assertIsNone(p.condicoes.codCargo)
        self.assertTrue(any(pend.codigo == CodigoPendencia.CADASTRO_INEXISTENTE for pend in p.pendencias))

    def test_llm_cai_apos_resolver_publico_preserva_loja(self):
        """No modo opcional de decisões por LLM, uma falha preserva os dados e gera TOOL_FALHA."""
        extracao = {
            "regras": [
                {
                    "trecho_origem": "3% para gerentes da loja 75 e 2% para vendedores",
                    "taxa_raw": "3%",
                    "cargo_raw": "gerentes",
                    "loja_raw": "75",
                },
                {
                    "trecho_origem": "2% para vendedores",
                    "taxa_raw": "2%",
                    "cargo_raw": "vendedores",
                }
            ],
            "vigencia_inicio_raw": "2026-12-01",
            "vigencia_fim_raw": "2026-12-31",
        }

        def h(req: httpx.Request):
            p = req.url.path
            if p.endswith("/cargos"):
                return httpx.Response(200, json={"encontrado": True, "itens": [{"codigo": 150, "descricao": "GERENTE DE LOJA"}]})
            if p.endswith("/lojas"):
                return httpx.Response(200, json={"encontrado": True, "itens": [{"codigo": 75, "descricao": "LOJA 75"}]})
            return httpx.Response(404)

        client = BackendClient(base_url="http://mock", timeout=1, transport=httpx.MockTransport(h))
        registry = criar_registry(client=client)

        provider = MagicMock()
        # 1ª chamada = extração com sucesso; 2ª chamada (decisão do laço) = LLMTimeoutError
        provider.complete.side_effect = [
            extracao,
            LLMTimeoutError("Timeout do provedor LLM"),
        ]

        agente = AgenteInterpretador(
            provider, registry, hooks=HooksAjusteSobreBase(), usar_llm_decisoes=True
        )
        res = agente.executar(InterpretarRequestV2(texto="3% para gerentes da loja 75 e 2% para vendedores"))
        self.assertEqual(provider.complete.call_count, 2)

        # Preservou as propostas extraídas
        self.assertEqual(len(res.propostas), 2)
        p1 = res.propostas[0]
        self.assertEqual(p1.condicoes.codLoja, 75)
        # TOOL_FALHA foi registrado em pendenciasGerais
        self.assertTrue(any(pend.codigo == CodigoPendencia.TOOL_FALHA for pend in res.pendenciasGerais))


if __name__ == "__main__":
    unittest.main()
