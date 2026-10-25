"""Regressão do modo opcional de decisões por LLM; modo padrão em test_agente_deterministico."""

import os
import sys
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from app.core.agente import AgenteInterpretador, Limites
from app.core.agente.hooks import HooksPadrao
from app.core.exceptions import LLMAuthenticationError, LLMTimeoutError
from app.schemas.proposta import InterpretarRequestV2
from app.tools import BackendClient, criar_registry

TEXTO = "3% para gerentes da loja 75 e a matrícula MATRIC-9 ganha 5% em dezembro"
EXTRACAO = {
    "regras": [
        {"trecho_origem": "3% para gerentes da loja 75", "taxa_raw": "3%", "cargo_raw": "gerentes", "loja_raw": "75"},
        {"trecho_origem": "a matrícula MATRIC-9 ganha 5%", "taxa_raw": "5%", "matricula_raw": "MATRIC-9"},
    ],
    "vigencia_inicio_raw": "dezembro", "vigencia_fim_raw": "dezembro",
}


def backend(overrides=None):
    """Backend falso; `overrides` mapeia sufixo de rota -> função(req) -> Response."""
    overrides = overrides or {}
    chamadas = []

    def h(req: httpx.Request):
        chamadas.append(req.url.path)
        for sufixo, fn in overrides.items():
            if req.url.path.endswith(sufixo):
                return fn(req)
        p = req.url.path
        if p.endswith("/cargos"):
            return httpx.Response(200, json={"encontrado": True, "itens": [
                {"codigo": 150, "descricao": "GERENTE DE LOJA"}, {"codigo": 151, "descricao": "GERENTE QUIOSQUE"}]})
        if p.endswith("/lojas"):
            return httpx.Response(200, json={"encontrado": True, "itens": [{"codigo": 75, "descricao": "LOJA 75"}]})
        if "/matriculas/" in p:
            return httpx.Response(200, json={"encontrado": True, "matricula": "MATRIC-9", "codLoja": 75,
                                             "codCargo": 100, "dataDemissao": None})
        if p.endswith("/regras-concorrentes"):
            return httpx.Response(200, json={"conflitos": []})
        return httpx.Response(404)

    client = BackendClient(base_url="http://b", timeout=1, transport=httpx.MockTransport(h))
    client.RETRY_BACKOFF_SECONDS = 0
    return client, chamadas


def llm(decisoes, extracao=EXTRACAO):
    """Provider falso: 1ª chamada devolve a extração, as seguintes as decisões na ordem."""
    prompts = []
    fila = list(decisoes)

    def complete(prompt, response_schema):
        prompts.append(prompt)
        if "PEDIDO DO GESTOR PARA PROCESSAR" in prompt:
            return extracao
        item = fila.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    p = MagicMock()
    p.complete.side_effect = complete
    p.prompts = prompts
    return p


def req(**kw):
    return InterpretarRequestV2(texto=kw.pop("texto", TEXTO), dataReferencia=date(2026, 9, 7), **kw)


def cod(bloco):
    return {p.codigo.value for p in bloco.pendencias}


@patch("app.core.config.settings.agent_use_llm_decisions", True)
class TestFluxoDemonstravel(unittest.TestCase):
    def test_analise_consulta_validacao(self):
        client, chamadas = backend()
        provider = llm([
            {"acao": "CONSULTAR", "lacunaId": "PUBLICO:p1", "ferramenta": "resolver_publico", "justificativa": "resolver cargo e loja"},
            {"acao": "CONSULTAR", "lacunaId": "MATRICULA:p2", "ferramenta": "validar_matricula", "justificativa": "validar matrícula"},
            {"acao": "FINALIZAR", "justificativa": "restam só consultas de concorrência"},
        ])
        r = AgenteInterpretador(provider, criar_registry(client)).executar(req())
        p1, p2 = r.propostas
        # loja resolvida pela consulta; cargo ambíguo virou pergunta ao usuário (não foi escolhido)
        self.assertEqual(p1.condicoes.codLoja, 75)
        self.assertIsNone(p1.condicoes.codCargo)
        self.assertIn("AMBIGUIDADE_CARGO", cod(p1))
        # matrícula validada: o bloco permanece sem inventar vínculos
        self.assertEqual(p2.condicoes.matricula, "MATRIC-9")
        self.assertIsNone(p2.condicoes.codLoja)
        self.assertEqual(r.status, "PROPOSTA_COM_PENDENCIAS")
        # rastreabilidade: ferramentas usadas, com status e bloco afetado
        self.assertEqual([e.ferramenta for e in r.trilhaFerramentas], ["resolver_publico", "validar_matricula"])
        self.assertEqual(r.trilhaFerramentas[0].blocosAfetados, ["p1"])
        self.assertEqual(r.propostas[0].referencias, [])  # ambíguo: nenhuma referência é registrada
        self.assertEqual(r.propostas[1].referencias[0].chave, {"matricula": "MATRIC-9"})
        self.assertEqual(r.propostas[0].evidencias[0].status, "AMBIGUO")

    def test_unica_lacuna_nao_gasta_llm(self):
        client, _ = backend()
        provider = llm([])  # qualquer chamada de decisão estouraria IndexError
        texto = "3% para vendedores da loja 75 em dezembro"
        ext = {"regras": [{"trecho_origem": "3% para vendedores da loja 75", "taxa_raw": "3%", "loja_raw": "75"}],
               "vigencia_inicio_raw": "dezembro"}
        provider = llm([], extracao=ext)
        r = AgenteInterpretador(provider, criar_registry(client)).executar(req(texto=texto))
        # a loja 75 já é extraída localmente (sem catálogo de lojas); só sobra concorrência: 1 lacuna
        self.assertEqual([e.ferramenta for e in r.trilhaFerramentas], ["consultar_regras_concorrentes"])
        self.assertEqual(provider.complete.call_count, 1)

    def test_conflito_de_regra_vira_pendencia(self):
        client, _ = backend({"/regras-concorrentes": lambda q: httpx.Response(
            200, json={"conflitos": [{"idRegra": 7, "taxa": "0.03", "especificidade": 8}]})})
        ext = {"regras": [{"trecho_origem": "3% para a loja 75", "taxa_raw": "3%", "loja_raw": "75"}],
               "vigencia_inicio_raw": "dezembro"}
        r = AgenteInterpretador(llm([], extracao=ext), criar_registry(client)).executar(req(texto="3% para a loja 75 em dezembro"))
        self.assertIn("CONFLITO_REGRA", cod(r.propostas[0]))

    def test_edicao_ignora_campanha_anterior(self):
        enviados = []

        def conc(q):
            enviados.append(q.read())
            return httpx.Response(200, json={"conflitos": []})

        client, _ = backend({"/regras-concorrentes": conc})
        ext = {"regras": [{"trecho_origem": "3% para a loja 75", "taxa_raw": "3%", "loja_raw": "75"}],
               "vigencia_inicio_raw": "dezembro"}
        from app.schemas.proposta import ContextoProposta
        ctx = ContextoProposta(campanhaId="camp-1", origem="VERSAO_EXISTENTE", substituiVersao="camp-1")
        AgenteInterpretador(llm([], extracao=ext), criar_registry(client)).executar(
            req(texto="3% para a loja 75 em dezembro", contexto=ctx))
        self.assertIn(b'"ignorarCampanhaId":"camp-1"', enviados[0].replace(b" ", b""))


@patch("app.core.config.settings.agent_use_llm_decisions", True)
class TestFalhas(unittest.TestCase):
    def test_falha_de_tool_nao_inventa_e_preserva(self):
        client, _ = backend({"/cargos": lambda q: httpx.Response(503), "/lojas": lambda q: httpx.Response(503)})
        provider = llm([
            {"acao": "CONSULTAR", "lacunaId": "PUBLICO:p1", "ferramenta": "resolver_publico", "justificativa": "x"},
            {"acao": "FINALIZAR", "justificativa": "x"},
        ])
        r = AgenteInterpretador(provider, criar_registry(client)).executar(req())
        p1 = r.propostas[0]
        self.assertIn("TOOL_FALHA", cod(p1))
        self.assertIsNone(p1.condicoes.codCargo)
        self.assertEqual(str(p1.taxa), "0.0300")  # o que já tinha foi preservado
        self.assertEqual(r.trilhaFerramentas[0].status, "FALHA")

    def test_cadastro_inexistente(self):
        client, _ = backend({"/lojas": lambda q: httpx.Response(200, json={"encontrado": False, "itens": []})})
        ext = {"regras": [{"trecho_origem": "3% para a loja Marte", "taxa_raw": "3%", "marca_raw": "FANTASMA"}],
               "vigencia_inicio_raw": "dezembro"}
        client2, _ = backend({"/marcas": lambda q: httpx.Response(200, json={"encontrado": False, "itens": []})})
        r = AgenteInterpretador(llm([], extracao=ext), criar_registry(client2)).executar(req(texto="3% para a loja Marte em dezembro"))
        self.assertIn("CADASTRO_INEXISTENTE", cod(r.propostas[0]))
        self.assertIsNone(r.propostas[0].condicoes.codMarca)

    def test_llm_cai_no_meio_preserva_apurado(self):
        client, _ = backend()
        provider = llm([
            {"acao": "CONSULTAR", "lacunaId": "PUBLICO:p1", "ferramenta": "resolver_publico", "justificativa": "x"},
            LLMTimeoutError(),
        ])
        r = AgenteInterpretador(provider, criar_registry(client)).executar(req())
        self.assertEqual(len(r.trilhaFerramentas), 1)
        self.assertEqual(r.propostas[0].condicoes.codLoja, 75)
        self.assertTrue(any(p.codigo.value == "TOOL_FALHA" for p in r.pendenciasGerais))

    def test_llm_cai_antes_de_conferir_publico_nao_apaga_a_condicao(self):
        client, chamadas = backend()
        ext = {"regras": [
            {"trecho_origem": "3% para vendedores da loja 75", "taxa_raw": "3%", "cargo_raw": "vendedores", "loja_raw": "75"},
            {"trecho_origem": "2% para gerentes de loja da marca PRETO", "taxa_raw": "2%",
             "cargo_raw": "gerentes de loja", "marca_raw": "PRETO"},
        ], "vigencia_inicio_raw": "dezembro"}
        provider = llm([LLMTimeoutError()], extracao=ext)
        r = AgenteInterpretador(provider, criar_registry(client)).executar(
            req(texto="3% para vendedores da loja 75 e 2% para gerentes de loja da marca PRETO em dezembro"))
        self.assertEqual(chamadas, [])
        for bloco in r.propostas:
            self.assertIn("TOOL_FALHA", cod(bloco))
        mensagens = " ".join(p.mensagem for b in r.propostas for p in b.pendencias)
        self.assertIn("vendedores", mensagens)
        self.assertIn("PRETO", mensagens)

    def test_erro_de_autenticacao_propaga(self):
        client, _ = backend()
        provider = llm([LLMAuthenticationError()])
        provider.complete.side_effect = LLMAuthenticationError()
        with self.assertRaises(LLMAuthenticationError):
            AgenteInterpretador(provider, criar_registry(client)).executar(req())

    def test_decisao_invalida_duas_vezes_encerra_com_pendencia(self):
        client, chamadas = backend()
        provider = llm([{"acao": "CONSULTAR", "lacunaId": "NAO:EXISTE", "ferramenta": "x"},
                        {"acao": "CONSULTAR", "lacunaId": "NAO:EXISTE", "ferramenta": "x"}])
        r = AgenteInterpretador(provider, criar_registry(client)).executar(req())
        self.assertEqual(chamadas, [])
        self.assertTrue(any(p.codigo.value == "LIMITE_AGENTE_ATINGIDO" for p in r.pendenciasGerais))

    def test_llm_nao_inventa_matricula_nos_argumentos(self):
        client, chamadas = backend()
        provider = llm([
            {"acao": "CONSULTAR", "lacunaId": "MATRICULA:p2", "ferramenta": "validar_matricula",
             "argumentos": {"matricula": "INVENTADA-1"}, "justificativa": "x"},
            {"acao": "FINALIZAR", "justificativa": "x"},
        ])
        AgenteInterpretador(provider, criar_registry(client)).executar(req())
        self.assertTrue(any(p.endswith("/matriculas/MATRIC-9") for p in chamadas))
        self.assertFalse(any("INVENTADA" in p for p in chamadas))


@patch("app.core.config.settings.agent_use_llm_decisions", True)
class TestLimites(unittest.TestCase):
    def test_max_tool_calls(self):
        client, chamadas = backend()
        provider = llm([{"acao": "CONSULTAR", "lacunaId": "PUBLICO:p1", "ferramenta": "resolver_publico", "justificativa": "x"}] * 5)
        r = AgenteInterpretador(provider, criar_registry(client), limites=Limites(max_tool_calls=1)).executar(req())
        self.assertEqual(len(r.trilhaFerramentas), 1)
        self.assertTrue(any("LIMITE_AGENTE_ATINGIDO" in cod(b) for b in r.propostas))
        self.assertEqual(r.status, "PROPOSTA_COM_PENDENCIAS")

    def test_max_steps(self):
        client, _ = backend()
        provider = llm([{"acao": "CONSULTAR", "lacunaId": "PUBLICO:p1", "ferramenta": "resolver_publico", "justificativa": "x"}] * 5)
        r = AgenteInterpretador(provider, criar_registry(client), limites=Limites(max_steps=2)).executar(req())
        self.assertLessEqual(len(r.trilhaFerramentas), 1)
        self.assertTrue(any("LIMITE_AGENTE_ATINGIDO" in cod(b) for b in r.propostas))

    def test_max_duration(self):
        client, _ = backend()
        t = {"v": 0.0}

        def relogio():
            t["v"] += 10.0  # cada leitura do relógio avança 10s
            return t["v"]

        provider = llm([{"acao": "CONSULTAR", "lacunaId": "PUBLICO:p1", "ferramenta": "resolver_publico", "justificativa": "x"}] * 5)
        r = AgenteInterpretador(provider, criar_registry(client), limites=Limites(max_duration_seconds=5), relogio=relogio).executar(req())
        self.assertEqual(r.trilhaFerramentas, [])
        self.assertTrue(any("LIMITE_AGENTE_ATINGIDO" in cod(b) for b in r.propostas))

    def test_nao_repete_consulta_igual(self):
        client, chamadas = backend()
        texto = "3% para gerentes da loja 75 e 4% para gerentes da loja 75 à noite em dezembro"
        ext = {"regras": [
            {"trecho_origem": "3% para gerentes da loja 75", "taxa_raw": "3%", "cargo_raw": "gerentes", "loja_raw": "75"},
            {"trecho_origem": "4% para gerentes da loja 75 à noite", "taxa_raw": "4%", "cargo_raw": "gerentes", "loja_raw": "75"},
        ], "vigencia_inicio_raw": "dezembro"}
        provider = llm([
            {"acao": "CONSULTAR", "lacunaId": "PUBLICO:p1", "ferramenta": "resolver_publico", "justificativa": "x"},
            {"acao": "CONSULTAR", "lacunaId": "PUBLICO:p2", "ferramenta": "resolver_publico", "justificativa": "x"},
            {"acao": "FINALIZAR", "justificativa": "x"},
        ] + [{"acao": "FINALIZAR", "justificativa": "x"}] * 3, extracao=ext)
        r = AgenteInterpretador(provider, criar_registry(client)).executar(req(texto=texto))
        self.assertEqual(sum(1 for c in chamadas if c.endswith("/cargos")), 1)  # reaproveitado
        reaproveitados = [e for e in r.trilhaFerramentas if "reaproveitado" in e.resumo]
        self.assertEqual(len(reaproveitados), 1)


@patch("app.core.config.settings.agent_use_llm_decisions", True)
class TestHooksEContrato(unittest.TestCase):
    def test_hooks_padrao_sao_identidade_e_hook_customizado_e_chamado(self):
        client, _ = backend()
        ext = {"regras": [{"trecho_origem": "3% para a loja 75", "taxa_raw": "3%", "loja_raw": "75"}],
               "vigencia_inicio_raw": "dezembro"}
        base = AgenteInterpretador(llm([], extracao=ext), criar_registry(client)).executar(req(texto="3% para a loja 75 em dezembro"))

        class Marca(HooksPadrao):
            visto = []

            def antes_de_fechar(self, blocos, ctx):
                self.visto.append(len(blocos))
                for b in blocos:
                    b.explicacao = "explicado"
                return blocos

        hook = Marca()
        r = AgenteInterpretador(llm([], extracao=ext), criar_registry(client), hooks=hook).executar(req(texto="3% para a loja 75 em dezembro"))
        self.assertEqual(hook.visto, [1])
        self.assertEqual(r.propostas[0].explicacao, "explicado")
        self.assertIsNone(base.propostas[0].explicacao)

    def test_resposta_nao_traz_controle_de_ativacao(self):
        client, _ = backend()
        ext = {"regras": [{"trecho_origem": "3% para a loja 75", "taxa_raw": "3%", "loja_raw": "75"}],
               "vigencia_inicio_raw": "dezembro"}
        r = AgenteInterpretador(llm([], extracao=ext), criar_registry(client)).executar(req(texto="3% para a loja 75 em dezembro"))
        dump = r.model_dump_json()
        for proibido in ("\"ativa\"", "\"publicad", "\"estado\"", "valorComissao", "protocolo"):
            self.assertNotIn(proibido, dump)

    def test_sem_proposta(self):
        client, _ = backend()
        r = AgenteInterpretador(llm([], extracao={"regras": []}), criar_registry(client)).executar(req(texto="bom dia"))
        self.assertEqual(r.status, "SEM_PROPOSTA")


if __name__ == "__main__":
    unittest.main()
