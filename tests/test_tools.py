"""Testes das ferramentas de consulta (IA-3): OK, SEM_DADOS, AMBIGUO e FALHA."""

import os
import sys
import unittest
from unittest.mock import patch

import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from app.tools import BackendClient, criar_registry
from app.tools.bases import ConsultarBaseComissao, ConsultarBaseArgs
from app.tools.cadastros import ResolverPublico, ResolverPublicoArgs, ValidarMatricula, ValidarMatriculaArgs
from app.tools.concorrencia import ConsultarRegrasConcorrentes, ConsultarConcorrenciaArgs
from app.tools.simulacao import ObterDadosSimulacao, DadosSimulacaoArgs


def cliente(handler) -> BackendClient:
    c = BackendClient(base_url="http://backend", timeout=1, transport=httpx.MockTransport(handler))
    c.RETRY_BACKOFF_SECONDS = 0
    return c


def json_resp(corpo, status=200):
    return httpx.Response(status, json=corpo)


class TestResolverPublico(unittest.TestCase):
    def test_ok_marca_e_cargo(self):
        def h(req):
            if req.url.path.endswith("/marcas"):
                return json_resp({"encontrado": True, "itens": [{"codigo": 10, "descricao": "PRETO"}]})
            return json_resp({"encontrado": True, "itens": [{"codigo": 100, "descricao": "VENDEDOR LOJA"}]})

        r = ResolverPublico(cliente(h)).executar(ResolverPublicoArgs(marca="preto", cargo="vendedor loja"))
        self.assertEqual(r.status, "OK")
        self.assertEqual(r.dados["dimensoes"]["marca"]["resolvido"]["codigo"], 10)
        self.assertEqual(len(r.referencias), 2)

    def test_cargo_ambiguo_nao_escolhe(self):
        def h(req):
            return json_resp({"encontrado": True, "itens": [
                {"codigo": 150, "descricao": "GERENTE DE LOJA"},
                {"codigo": 150, "descricao": "GERENTE QUIOSQUE"},
            ]})

        r = ResolverPublico(cliente(h)).executar(ResolverPublicoArgs(cargo="gerentes"))
        self.assertEqual(r.status, "AMBIGUO")
        self.assertEqual(len(r.dados["dimensoes"]["cargo"]["candidatos"]), 2)
        self.assertEqual(r.referencias, [])

    def test_match_exato_desambigua(self):
        def h(req):
            return json_resp({"encontrado": True, "itens": [
                {"codigo": 100, "descricao": "VENDEDOR"},
                {"codigo": 101, "descricao": "VENDEDOR LOJA"},
            ]})

        r = ResolverPublico(cliente(h)).executar(ResolverPublicoArgs(cargo="vendedor"))
        self.assertEqual(r.status, "OK")
        self.assertEqual(r.dados["dimensoes"]["cargo"]["resolvido"]["codigo"], 100)

    def test_sem_dados(self):
        r = ResolverPublico(cliente(lambda req: json_resp({"encontrado": False, "itens": []}))).executar(
            ResolverPublicoArgs(loja="999")
        )
        self.assertEqual(r.status, "SEM_DADOS")
        self.assertIsNone(r.erro)

    def test_codigo_numerico_usa_parametro_codigo(self):
        vistos = {}

        def h(req):
            vistos.update(dict(req.url.params))
            return json_resp({"encontrado": True, "itens": [{"codigo": 75, "descricao": "LOJA 75"}]})

        ResolverPublico(cliente(h)).executar(ResolverPublicoArgs(loja="75"))
        self.assertEqual(vistos, {"codigo": "75"})

    def test_falha_nao_vira_sem_dados(self):
        r = ResolverPublico(cliente(lambda req: httpx.Response(503))).executar(ResolverPublicoArgs(marca="PRETO"))
        self.assertEqual(r.status, "FALHA")
        self.assertEqual(r.erro.tipo, "HTTP_503")
        self.assertIsNone(r.dados)

    def test_falha_parcial_preserva_resolvido(self):
        def h(req):
            if req.url.path.endswith("/marcas"):
                return json_resp({"encontrado": True, "itens": [{"codigo": 10, "descricao": "PRETO"}]})
            return httpx.Response(500)

        r = ResolverPublico(cliente(h)).executar(ResolverPublicoArgs(marca="PRETO", cargo="X"))
        self.assertEqual(r.status, "FALHA")
        self.assertEqual(r.dados["dimensoes"]["marca"]["status"], "OK")
        self.assertEqual(r.dados["dimensoes"]["cargo"]["status"], "FALHA")


class TestValidarMatricula(unittest.TestCase):
    def test_ok(self):
        r = ValidarMatricula(cliente(lambda req: json_resp({"encontrado": True, "matricula": "MATRIC-1", "codLoja": 75}))).executar(
            ValidarMatriculaArgs(matricula="MATRIC-1")
        )
        self.assertEqual(r.status, "OK")
        self.assertEqual(r.referencias[0].chave, {"matricula": "MATRIC-1"})

    def test_inexistente(self):
        r = ValidarMatricula(cliente(lambda req: json_resp({"encontrado": False}))).executar(
            ValidarMatriculaArgs(matricula="X")
        )
        self.assertEqual(r.status, "SEM_DADOS")

    def test_json_invalido(self):
        r = ValidarMatricula(cliente(lambda req: httpx.Response(200, text="nao e json"))).executar(
            ValidarMatriculaArgs(matricula="X")
        )
        self.assertEqual(r.status, "FALHA")
        self.assertEqual(r.erro.tipo, "RESPOSTA_INVALIDA")

    def test_timeout(self):
        def h(req):
            raise httpx.ReadTimeout("lento")

        r = ValidarMatricula(cliente(h)).executar(ValidarMatriculaArgs(matricula="X"))
        self.assertEqual(r.status, "FALHA")
        self.assertEqual(r.erro.tipo, "TIMEOUT")
        self.assertEqual(r.erro.detalhe, "ReadTimeout")


class TestBackendClientRetry(unittest.TestCase):
    def test_5xx_retenta_uma_vez_e_4xx_nao(self):
        chamadas = []

        def h5(req):
            chamadas.append(1)
            return httpx.Response(500)

        ValidarMatricula(cliente(h5)).executar(ValidarMatriculaArgs(matricula="X"))
        self.assertEqual(len(chamadas), 2)

        chamadas.clear()

        def h4(req):
            chamadas.append(1)
            return httpx.Response(400, text="ruim")

        r = ValidarMatricula(cliente(h4)).executar(ValidarMatriculaArgs(matricula="X"))
        self.assertEqual(len(chamadas), 1)
        self.assertEqual(r.erro.tipo, "HTTP_400")

    def test_recupera_na_segunda_tentativa(self):
        estado = {"n": 0}

        def h(req):
            estado["n"] += 1
            if estado["n"] == 1:
                return httpx.Response(502)
            return json_resp({"encontrado": False})

        r = ValidarMatricula(cliente(h)).executar(ValidarMatriculaArgs(matricula="X"))
        self.assertEqual(r.status, "SEM_DADOS")


class TestBaseEConcorrencia(unittest.TestCase):
    def test_base_ok_e_referencia(self):
        r = ConsultarBaseComissao(cliente(lambda req: json_resp(
            {"encontrado": True, "taxa": "0.0250", "competenciaUsada": "2026-09"}
        ))).executar(ConsultarBaseArgs(codMarca=10, codCargo=100, competencia="2026-10"))
        self.assertEqual(r.status, "OK")
        self.assertEqual(str(r.referencias[0].taxaBase), "0.0250")
        self.assertEqual(r.referencias[0].chave["competencia"], "2026-09")

    def test_base_ausente_nao_inventa_taxa(self):
        r = ConsultarBaseComissao(cliente(lambda req: json_resp({"encontrado": False}))).executar(
            ConsultarBaseArgs(codMarca=10, codCargo=100, competencia="2026-10")
        )
        self.assertEqual(r.status, "SEM_DADOS")
        self.assertIsNone(r.dados)
        self.assertEqual(r.referencias, [])

    def test_base_taxa_invalida(self):
        r = ConsultarBaseComissao(cliente(lambda req: json_resp({"encontrado": True, "taxa": "abc"}))).executar(
            ConsultarBaseArgs(codMarca=10, codCargo=100, competencia="2026-10")
        )
        self.assertEqual(r.status, "FALHA")

    def test_concorrencia(self):
        corpo = {}

        def h(req):
            corpo.update(__import__("json").loads(req.content))
            return json_resp({"conflitos": [{"idRegra": 7, "taxa": "0.03", "especificidade": 8}]})

        r = ConsultarRegrasConcorrentes(cliente(h)).executar(
            ConsultarConcorrenciaArgs.model_validate(
                {"condicoes": {"codLoja": 75}, "dataInicio": "2026-10-01", "ignorarCampanhaId": "c1"}
            )
        )
        self.assertEqual(r.status, "OK")
        self.assertEqual(corpo["ignorarCampanhaId"], "c1")
        self.assertEqual(corpo["condicoes"], {"codLoja": 75})
        self.assertEqual(r.referencias[0].chave, {"idRegra": 7})

    def test_concorrencia_sem_conflito(self):
        r = ConsultarRegrasConcorrentes(cliente(lambda req: json_resp({"conflitos": []}))).executar(
            ConsultarConcorrenciaArgs()
        )
        self.assertEqual(r.status, "SEM_DADOS")


class TestDadosSimulacaoEArgumentos(unittest.TestCase):
    def test_pagina_ate_ultima(self):
        def h(req):
            p = int(req.url.params["page"])
            return json_resp({"content": [{"id": f"v{p}"}], "last": p == 1})

        r = ObterDadosSimulacao(cliente(h)).executar(DadosSimulacaoArgs(competencia="2026-10"))
        self.assertEqual(r.dados["total"], 2)

    def test_limite_de_registros(self):
        with patch("app.tools.simulacao.settings.sim_max_registros", 1):
            r = ObterDadosSimulacao(cliente(lambda req: json_resp({"content": [{}, {}], "last": True}))).executar(
                DadosSimulacaoArgs(competencia="2026-10")
            )
        self.assertEqual(r.status, "FALHA")
        self.assertEqual(r.erro.tipo, "LIMITE_REGISTROS")

    def test_argumentos_invalidos_do_llm_nao_executam(self):
        chamadas = []
        reg = criar_registry(cliente(lambda req: chamadas.append(1) or json_resp({})))
        r = reg.obter("consultar_base_comissao").executar_dict({"codMarca": "x"})
        self.assertEqual(r.status, "FALHA")
        self.assertEqual(r.erro.tipo, "ARGUMENTOS_INVALIDOS")
        self.assertEqual(chamadas, [])


if __name__ == "__main__":
    unittest.main()
