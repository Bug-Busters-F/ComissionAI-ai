"""
Testes da tarefa IA-8 (BUG-71):
Reutilizar e validar o agente na edição de campanhas versionadas.
"""

import json
import os
import sys
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from app.core.agente import AgenteInterpretador
from app.core.agente.hooks import HooksAjusteSobreBase
from app.core.services.reinterpretador import ServicoReinterpretacao
from app.schemas.proposta import (
    BlocoProposta,
    Condicoes,
    ContextoProposta,
    InterpretarRequestV2,
    ReinterpretarRequest,
)
from app.tools import BackendClient, criar_registry
from app.tools.base import ToolRegistry


class TestIA8Versionamento(unittest.TestCase):
    """Testes de campanhas versionadas (origem=VERSAO_EXISTENTE)."""

    def test_versao_existente_nao_conflita_consigo_mesma(self):
        """Quando origem=VERSAO_EXISTENTE, a consulta de concorrência DEVE enviar ignorarCampanhaId."""
        extracao = {
            "regras": [
                {
                    "trecho_origem": "3% para gerentes da loja 75",
                    "taxa_raw": "3%",
                    "cargo_raw": "gerentes",
                    "loja_raw": "75",
                }
            ],
            "vigencia_inicio_raw": "2026-12-01",
            "vigencia_fim_raw": "2026-12-31",
        }

        chamadas_concorrencia = []

        def h(req: httpx.Request):
            p = req.url.path
            if p.endswith("/cargos"):
                return httpx.Response(200, json={"encontrado": True, "itens": [{"codigo": 150, "descricao": "GERENTE"}]})
            if p.endswith("/lojas"):
                return httpx.Response(200, json={"encontrado": True, "itens": [{"codigo": 75, "descricao": "LOJA 75"}]})
            if p.endswith("/regras-concorrentes"):
                corpo = json.loads(req.content.decode("utf-8"))
                chamadas_concorrencia.append(corpo)
                return httpx.Response(200, json={"conflitos": []})
            return httpx.Response(404)

        client = BackendClient(base_url="http://mock", timeout=1, transport=httpx.MockTransport(h))
        registry = criar_registry(client=client)

        provider = MagicMock()
        provider.complete.return_value = extracao

        agente = AgenteInterpretador(provider, registry, hooks=HooksAjusteSobreBase())

        req = InterpretarRequestV2(
            texto="3% para gerentes da loja 75 em dezembro",
            contexto=ContextoProposta(
                origem="VERSAO_EXISTENTE",
                campanhaId="camp-12",
                revisao=2,
            ),
        )

        res = agente.executar(req)
        self.assertEqual(len(chamadas_concorrencia), 1)
        self.assertEqual(chamadas_concorrencia[0].get("ignorarCampanhaId"), "camp-12")
        self.assertEqual(res.contexto.origem, "VERSAO_EXISTENTE")

    def test_substitui_versao_diferente_da_campanha_id(self):
        """substituiVersao deve ter precedência sobre campanhaId ao definir ignorarCampanhaId."""
        extracao = {
            "regras": [
                {
                    "trecho_origem": "3% para gerentes da loja 75",
                    "taxa_raw": "3%",
                    "cargo_raw": "gerentes",
                    "loja_raw": "75",
                }
            ],
            "vigencia_inicio_raw": "2026-12-01",
            "vigencia_fim_raw": "2026-12-31",
        }

        chamadas_concorrencia = []

        def h(req: httpx.Request):
            p = req.url.path
            if p.endswith("/cargos"):
                return httpx.Response(200, json={"encontrado": True, "itens": [{"codigo": 150, "descricao": "GERENTE"}]})
            if p.endswith("/lojas"):
                return httpx.Response(200, json={"encontrado": True, "itens": [{"codigo": 75, "descricao": "LOJA 75"}]})
            if p.endswith("/regras-concorrentes"):
                corpo = json.loads(req.content.decode("utf-8"))
                chamadas_concorrencia.append(corpo)
                return httpx.Response(200, json={"conflitos": []})
            return httpx.Response(404)

        client = BackendClient(base_url="http://mock", timeout=1, transport=httpx.MockTransport(h))
        registry = criar_registry(client=client)

        provider = MagicMock()
        provider.complete.return_value = extracao

        agente = AgenteInterpretador(provider, registry, hooks=HooksAjusteSobreBase())

        req = InterpretarRequestV2(
            texto="3% para gerentes da loja 75 em dezembro",
            contexto=ContextoProposta(
                origem="VERSAO_EXISTENTE",
                campanhaId="camp-nova",
                substituiVersao="camp-v1",
                revisao=2,
            ),
        )

        agente.executar(req)
        self.assertEqual(len(chamadas_concorrencia), 1)
        self.assertEqual(chamadas_concorrencia[0].get("ignorarCampanhaId"), "camp-v1")

    def test_versao_existente_reinterpretar_preserva_outros_blocos(self):
        """Ao reinterpretar uma versão existente, apenas o bloco indicado é substituído."""
        saida_llm = {
            "regras": [
                {"trecho_origem": "3.5% para gerentes da loja 75", "taxa_raw": "3.5%", "cargo_raw": "gerentes", "loja_raw": "75"}
            ],
            "vigencia_inicio_raw": "2026-12-01",
            "vigencia_fim_raw": "2026-12-31",
        }

        provider = MagicMock()
        provider.complete.return_value = saida_llm

        agente = AgenteInterpretador(provider, ToolRegistry(), hooks=HooksAjusteSobreBase())
        servico = ServicoReinterpretacao(agente)

        bloco_v1 = BlocoProposta(
            idLocal="p1",
            taxa=Decimal("0.0300"),
            condicoes=Condicoes(codCargo=150, codLoja=75),
            dataInicio=date(2026, 12, 1),
            dataFim=date(2026, 12, 31),
        )
        outro_bloco = BlocoProposta(
            idLocal="p2",
            taxa=Decimal("0.0500"),
            condicoes=Condicoes(codCargo=100),
            dataInicio=date(2026, 12, 1),
            dataFim=date(2026, 12, 31),
        )

        req = ReinterpretarRequest(
            contexto=ContextoProposta(
                origem="VERSAO_EXISTENTE",
                campanhaId="camp-12",
                revisao=2,
            ),
            idLocal="p1",
            textoAlterado="3.5% para gerentes da loja 75",
            blocoAtual=bloco_v1,
            demaisBlocos=[outro_bloco],
        )

        resp = servico.reinterpretar(req)
        self.assertEqual(len(resp.propostasSubstituicao), 1)
        self.assertEqual(resp.propostasSubstituicao[0].idLocal, "p1")
        self.assertEqual(resp.propostasSubstituicao[0].taxa, Decimal("0.0350"))
        # outro_bloco não foi alterado
        self.assertEqual(outro_bloco.taxa, Decimal("0.0500"))
        self.assertEqual(outro_bloco.idLocal, "p2")

    def test_resposta_nao_contem_campos_de_ativacao_versao_existente(self):
        """A resposta nunca deve conter campos de controle de banco / apuração."""
        bloco = BlocoProposta(
            idLocal="p1",
            taxa=Decimal("0.0300"),
            dataInicio=date(2026, 12, 1),
            dataFim=date(2026, 12, 31),
        )
        json_bloco = bloco.model_dump_json()
        for campo_proibido in ("publicad", "estado", "valorComissao", "protocolo", "versao"):
            self.assertNotIn(f'"{campo_proibido}"', json_bloco)


if __name__ == "__main__":
    unittest.main()
