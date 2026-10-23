"""
Testes unitários e de integração para IA-5 (BUG-56):
Ajustes sobre a comissão base e validação de propostas e ambiguidades.
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
from app.core.normalizers.taxa import calcular_taxa_com_operacao, interpretar_operacao, normalizar_operacao
from app.schemas.proposta import CodigoPendencia, ContextoProposta, InterpretarRequestV2
from app.tools import BackendClient, criar_registry


class TestNormalizadorOperacao(unittest.TestCase):
    """Testes determinísticos do normalizador de operações sobre a base."""

    def test_adicionar_pp(self):
        tipo, delta, p = normalizar_operacao("mais 1 ponto percentual")
        self.assertEqual(tipo, "ADICIONAR_PP")
        self.assertEqual(delta, Decimal("0.0100"))
        self.assertEqual(p, [])

        tipo, delta, p = normalizar_operacao("+ 1.5 pp")
        self.assertEqual(tipo, "ADICIONAR_PP")
        self.assertEqual(delta, Decimal("0.0150"))

    def test_reduzir_pp(self):
        tipo, delta, p = normalizar_operacao("menos 0,5 pontos percentuais")
        self.assertEqual(tipo, "REDUZIR_PP")
        self.assertEqual(delta, Decimal("0.0050"))
        self.assertEqual(p, [])

        tipo, delta, p = normalizar_operacao("-0.5 pp")
        self.assertEqual(tipo, "REDUZIR_PP")
        self.assertEqual(delta, Decimal("0.0050"))

    def test_aumentar_percentual_relativo(self):
        tipo, delta, p = normalizar_operacao("aumentar 1% sobre a base")
        self.assertEqual(tipo, "AUMENTAR_PERCENTUAL")
        self.assertEqual(delta, Decimal("0.0100"))
        self.assertEqual(p, [])

    def test_reduzir_percentual_relativo(self):
        tipo, delta, p = normalizar_operacao("reduzir 1% sobre a base")
        self.assertEqual(tipo, "REDUZIR_PERCENTUAL")
        self.assertEqual(delta, Decimal("0.0100"))
        self.assertEqual(p, [])

    def test_taxa_absoluta(self):
        tipo, val, p = normalizar_operacao("3%")
        self.assertEqual(tipo, "TAXA_ABSOLUTA")
        self.assertEqual(val, Decimal("0.0300"))
        self.assertEqual(p, [])

    def test_expressoes_ambiguas_nao_viram_taxa(self):
        # '%' com 'mais'/'+' não distingue pontos percentuais de variação relativa
        for expr in ("mais 1%", "base + 1%", "1% a mais que a base", "acréscimo de 1% sobre a base", "base menos 10%"):
            with self.subTest(expr=expr):
                r = interpretar_operacao(expr)
                self.assertIsNone(r.tipo)
                self.assertIsNone(r.valor)
                self.assertTrue(r.ambigua)
                self.assertIn("ambígua", r.pendencias[0])

    def test_pp_sem_sentido_e_ambiguo(self):
        r = interpretar_operacao("1 pp")
        self.assertIsNone(r.tipo)
        self.assertTrue(r.ambigua)

    def test_variantes_reconhecidas(self):
        casos = {
            "reduzir 2 pontos": ("REDUZIR_PP", Decimal("0.0200")),
            "aumento de 10% na comissão": ("AUMENTAR_PERCENTUAL", Decimal("0.1000")),
            "redução de 5% na base": ("REDUZIR_PERCENTUAL", Decimal("0.0500")),
            "aumentar relativamente 1%": ("AUMENTAR_PERCENTUAL", Decimal("0.0100")),
            "1 p.p. a mais": ("ADICIONAR_PP", Decimal("0.0100")),
        }
        for expr, (tipo, valor) in casos.items():
            with self.subTest(expr=expr):
                self.assertEqual(normalizar_operacao(expr)[:2], (tipo, valor))

    def test_operacao_invalida_gera_pendencia(self):
        tipo, val, p = normalizar_operacao("ajustar valor")
        self.assertIsNone(tipo)
        self.assertIsNone(val)
        self.assertTrue(len(p) > 0)


class TestCalculoTaxaComOperacao(unittest.TestCase):
    """Testes dos cálculos matemáticos de ajuste sobre comissão base."""

    def test_adicionar_pp_sobre_base(self):
        # Base 2.5% + 1pp = 3.5%
        base = Decimal("0.0250")
        taxa = calcular_taxa_com_operacao(base, "ADICIONAR_PP", Decimal("0.0100"))
        self.assertEqual(taxa, Decimal("0.0350"))

    def test_reduzir_pp_sobre_base(self):
        # Base 2.5% - 0.5pp = 2.0%
        base = Decimal("0.0250")
        taxa = calcular_taxa_com_operacao(base, "REDUZIR_PP", Decimal("0.0050"))
        self.assertEqual(taxa, Decimal("0.0200"))

    def test_aumentar_percentual_relativo(self):
        # Base 2.5% + 1% relativo = 2.525% -> 0.0253 com ROUND_HALF_UP escala 4
        base = Decimal("0.0250")
        taxa_exata = calcular_taxa_com_operacao(base, "AUMENTAR_PERCENTUAL", Decimal("0.0100"), arredondar=False)
        self.assertEqual(taxa_exata, Decimal("0.02525"))
        taxa_arredondada = calcular_taxa_com_operacao(base, "AUMENTAR_PERCENTUAL", Decimal("0.0100"), arredondar=True)
        self.assertEqual(taxa_arredondada, Decimal("0.0253"))

    def test_reduzir_percentual_relativo(self):
        # Base 2.5% - 1% relativo = 2.475% -> 0.0248 com ROUND_HALF_UP escala 4
        base = Decimal("0.0250")
        taxa_exata = calcular_taxa_com_operacao(base, "REDUZIR_PERCENTUAL", Decimal("0.0100"), arredondar=False)
        self.assertEqual(taxa_exata, Decimal("0.02475"))
        taxa_arredondada = calcular_taxa_com_operacao(base, "REDUZIR_PERCENTUAL", Decimal("0.0100"), arredondar=True)
        self.assertEqual(taxa_arredondada, Decimal("0.0248"))


class TestIntegracaoAgenteAjusteBase(unittest.TestCase):
    """Testes de ponta a ponta do laço do agente executando HooksAjusteSobreBase."""

    def test_agente_calcula_adicionar_pp_com_sucesso(self):
        # Simula extração contendo operacao_raw
        extracao = {
            "regras": [
                {
                    "trecho_origem": "mais 1 ponto percentual para vendedores da marca 10 em dezembro",
                    "operacao_raw": "mais 1 ponto percentual",
                    "cargo_raw": "vendedores",
                    "marca_raw": "10",
                }
            ],
            "vigencia_inicio_raw": "2026-12-01",
            "vigencia_fim_raw": "2026-12-31",
        }

        # Mock backend: resolve cargos e base
        def h(req: httpx.Request):
            p = req.url.path
            if p.endswith("/cargos"):
                return httpx.Response(200, json={"encontrado": True, "itens": [{"codigo": 100, "descricao": "VENDEDOR"}]})
            if p.endswith("/marcas"):
                return httpx.Response(200, json={"encontrado": True, "itens": [{"codigo": 10, "descricao": "MARCA 10"}]})
            if p.endswith("/bases"):
                return httpx.Response(200, json={"encontrado": True, "taxa": "0.0250", "competenciaUsada": "2026-12"})
            if p.endswith("/regras-concorrentes"):
                return httpx.Response(200, json={"conflitos": []})
            return httpx.Response(404)

        client = BackendClient(base_url="http://mock-backend", timeout=1, transport=httpx.MockTransport(h))
        registry = criar_registry(client=client)

        provider = MagicMock()
        provider.complete.return_value = extracao

        agente = AgenteInterpretador(provider, registry, hooks=HooksAjusteSobreBase())

        req = InterpretarRequestV2(
            texto="mais 1 ponto percentual para vendedores da marca 10 em dezembro",
            competencia="2026-12",
            contexto=ContextoProposta(campanhaId="camp-10", revisao=1),
        )

        res = agente.executar(req)
        self.assertEqual(len(res.propostas), 1)
        p = res.propostas[0]
        # Base 0.0250 + 1pp (0.0100) -> 0.0350
        self.assertEqual(p.taxa, Decimal("0.0350"))
        # a operação original continua rastreável (tipo + delta); a taxa final fica em `taxa`
        self.assertEqual(p.operacao.tipo, "ADICIONAR_PP")
        self.assertEqual(p.operacao.valor, Decimal("0.0100"))
        self.assertIn("2,50%", p.explicacao)
        self.assertIn("+1,00 p.p.", p.explicacao)
        self.assertIn("3,50%", p.explicacao)
        # Verifica se referência à base foi registrada
        self.assertTrue(any(ref.fonte == "BASE_COMISS" for ref in p.referencias))
        # Verifica que pendência CAMPO_AUSENTE da taxa foi removida
        self.assertFalse(any(pend.codigo == CodigoPendencia.CAMPO_AUSENTE and pend.campo == "taxa" for pend in p.pendencias))

    def test_base_ausente_mantem_pendencia(self):
        extracao = {
            "regras": [
                {
                    "trecho_origem": "mais 1 pp para vendedores da marca 10 em dezembro",
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
            if p.endswith("/regras-concorrentes"):
                return httpx.Response(200, json={"conflitos": []})
            return httpx.Response(404)

        client = BackendClient(base_url="http://mock-backend", timeout=1, transport=httpx.MockTransport(h))
        registry = criar_registry(client=client)

        provider = MagicMock()
        provider.complete.return_value = extracao

        agente = AgenteInterpretador(provider, registry, hooks=HooksAjusteSobreBase())

        req = InterpretarRequestV2(
            texto="mais 1 pp para vendedores da marca 10 em dezembro",
            competencia="2026-12",
        )

        res = agente.executar(req)
        self.assertEqual(len(res.propostas), 1)
        p = res.propostas[0]
        self.assertIsNone(p.taxa)
        self.assertTrue(any(pend.codigo == CodigoPendencia.BASE_AUSENTE for pend in p.pendencias))

    def test_multiplas_bases_gera_ambiguidade(self):
        extracao = {
            "regras": [
                {
                    "trecho_origem": "mais 1 pp para vendedores da marca 10 em dezembro",
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
                # Retorna indicador de multiplas bases
                return httpx.Response(200, json={"encontrado": True, "multiplasBases": True, "itens": [{"taxa": "0.02"}, {"taxa": "0.03"}]})
            if p.endswith("/regras-concorrentes"):
                return httpx.Response(200, json={"conflitos": []})
            return httpx.Response(404)

        client = BackendClient(base_url="http://mock-backend", timeout=1, transport=httpx.MockTransport(h))
        registry = criar_registry(client=client)

        provider = MagicMock()
        provider.complete.return_value = extracao

        agente = AgenteInterpretador(provider, registry, hooks=HooksAjusteSobreBase())

        req = InterpretarRequestV2(
            texto="mais 1 pp para vendedores da marca 10 em dezembro",
            competencia="2026-12",
        )

        res = agente.executar(req)
        p = res.propostas[0]
        self.assertIsNone(p.taxa)
        self.assertTrue(
            any(
                pend.codigo == CodigoPendencia.AMBIGUIDADE_PUBLICO and "múltiplas bases" in pend.mensagem.lower()
                for pend in p.pendencias
            )
        )


def _backend(bases_json=None):
    """Spring falso: cargo VENDEDOR (100), marca 10, base configurável e sem concorrência."""

    def h(req: httpx.Request):
        p = req.url.path
        if p.endswith("/cargos"):
            return httpx.Response(200, json={"encontrado": True, "itens": [{"codigo": 100, "descricao": "VENDEDOR"}]})
        if p.endswith("/marcas"):
            return httpx.Response(200, json={"encontrado": True, "itens": [{"codigo": 10, "descricao": "MARCA 10"}]})
        if p.endswith("/bases"):
            return httpx.Response(200, json=bases_json or {"encontrado": True, "taxa": "0.0250"})
        if p.endswith("/regras-concorrentes"):
            return httpx.Response(200, json={"conflitos": []})
        return httpx.Response(404)

    client = BackendClient(base_url="http://mock-backend", timeout=1, transport=httpx.MockTransport(h))
    return criar_registry(client=client)


def _executar(regra, registry=None):
    provider = MagicMock()
    provider.complete.return_value = {
        "regras": [regra], "vigencia_inicio_raw": "2026-12-01", "vigencia_fim_raw": "2026-12-31",
    }
    agente = AgenteInterpretador(provider, registry or _backend(), hooks=HooksAjusteSobreBase())
    return agente.executar(InterpretarRequestV2(texto=regra["trecho_origem"], competencia="2026-12"))


class TestAjusteSobreBaseCasosDeBorda(unittest.TestCase):
    def test_relativo_fixa_taxa_com_precisao_acordada(self):
        res = _executar({"trecho_origem": "aumentar 1% sobre a base para vendedores da marca 10",
                         "operacao_raw": "aumentar 1% sobre a base", "cargo_raw": "vendedores", "marca_raw": "10"})
        p = res.propostas[0]
        self.assertEqual(p.taxa, Decimal("0.0253"))  # 2,525% em escala 4 HALF_UP
        self.assertEqual((p.operacao.tipo, p.operacao.valor), ("AUMENTAR_PERCENTUAL", Decimal("0.0100")))
        ref = next(r for r in p.referencias if r.fonte == "BASE_COMISS")
        self.assertEqual(ref.taxaBase, Decimal("0.0250"))

    def test_expressao_ambigua_gera_pendencia_sem_taxa(self):
        res = _executar({"trecho_origem": "mais 1% para vendedores da marca 10",
                         "operacao_raw": "mais 1%", "cargo_raw": "vendedores", "marca_raw": "10"})
        p = res.propostas[0]
        self.assertIsNone(p.taxa)
        self.assertIsNone(p.operacao)
        amb = [x for x in p.pendencias if x.codigo == CodigoPendencia.TAXA_INVALIDA and x.campo == "taxa"]
        self.assertTrue(amb and amb[0].pergunta)
        self.assertEqual(res.status, "PROPOSTA_COM_PENDENCIAS")

    def test_operacao_com_valor_absoluto_fixa_taxa(self):
        res = _executar({"trecho_origem": "3% para vendedores da marca 10",
                         "operacao_raw": "3%", "cargo_raw": "vendedores", "marca_raw": "10"})
        p = res.propostas[0]
        self.assertEqual(p.taxa, Decimal("0.0300"))
        self.assertEqual(p.operacao.tipo, "TAXA_ABSOLUTA")
        self.assertFalse(any(x.campo == "taxa" for x in p.pendencias))

    def test_publico_sem_marca_pede_restricao(self):
        # sem marca, cada marca teria sua base: não há taxa única para o ajuste
        res = _executar({"trecho_origem": "mais 1 pp para vendedores",
                         "operacao_raw": "mais 1 pp", "cargo_raw": "vendedores"})
        p = res.propostas[0]
        self.assertIsNone(p.taxa)
        pend = [x for x in p.pendencias if x.codigo == CodigoPendencia.AMBIGUIDADE_PUBLICO]
        self.assertEqual(len(pend), 1)
        self.assertIn("marca", pend[0].pergunta)
        self.assertFalse(any(x.codigo == CodigoPendencia.CAMPO_AUSENTE and x.campo == "taxa" for x in p.pendencias))

    def test_resultado_fora_do_intervalo_gera_taxa_invalida(self):
        res = _executar({"trecho_origem": "menos 5 pp para vendedores da marca 10",
                         "operacao_raw": "menos 5 pp", "cargo_raw": "vendedores", "marca_raw": "10"})
        p = res.propostas[0]
        self.assertIsNone(p.taxa)
        self.assertTrue(any(x.codigo == CodigoPendencia.TAXA_INVALIDA for x in p.pendencias))


if __name__ == "__main__":
    unittest.main()
