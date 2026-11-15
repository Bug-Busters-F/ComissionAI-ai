"""
IA-10 (BUG-123): `POST /api/v2/executar-programa` no contrato que o backend já usa
(`AiServiceClient.executarProgramaPython`, BACK-9/BACK-11 e apuração definitiva).

O programa abaixo segue byte a byte o formato de `CampanhaProgramaPythonService.gerarCodigoConsolidado`
e as vendas seguem `montarVendaParaPython` (números como double, `taxa_base`, `ignorar_vigencia`).
"""

import hashlib
import os
import sys
import unittest
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from app.core.config import settings  # noqa: E402
from app.core.simulacao.validador import validar_programa  # noqa: E402
from app.main import app  # noqa: E402

ROTA = "/api/v2/executar-programa"
GOLDEN_PROGRAMA = os.path.join(os.path.dirname(__file__), "golden", "programa_backend_gerarCodigoConsolidado.py.txt")

PROGRAMA_BACKEND = """# ===================================================================
# Programa Executável da Campanha: Natal
# Período de Vigência: 2025-11-01 até 2025-11-30
# Versão da Campanha: 3
# ===================================================================
from decimal import Decimal, ROUND_HALF_UP

def calcular_comissao(venda: dict) -> float | None:
    \"\"\"Calcula a comissão para um registro de venda segundo as regras da campanha.\"\"\"
    data_raw = venda.get('data_venda') if venda.get('data_venda') is not None else venda.get('dataVenda', '')
    data_venda = str(data_raw)[:10]
    if not venda.get('ignorar_vigencia') and not ('2025-11-01' <= data_venda <= '2025-11-30'):
        return None

    valor_raw = venda.get('valor_venda')
    if valor_raw is None:
        valor_raw = venda.get('valor')
    if valor_raw is None:
        return None
    valor = Decimal(str(valor_raw))
    if valor <= 0:
        return None

    centavo = Decimal('0.01')
    taxa_base_raw = venda.get('taxa_base')
    taxa_base_venda = Decimal(str(taxa_base_raw)) if taxa_base_raw is not None else None

    # Regra 1: b1 - Loja 75 acima de mil
    if venda.get('cod_loja') == 75 and valor >= Decimal('1000'):
        # Operação: ACRESCIMO_PONTOS
        ajuste = Decimal('0.01')
        taxa = (taxa_base_venda + ajuste) if taxa_base_venda is not None else Decimal('0.035')
        comissao = (valor * taxa).quantize(centavo, rounding=ROUND_HALF_UP)
        return float(comissao)

    # Regra 2: b2 - Marca 10
    if venda.get('cod_marca') == 10:
        # Operação: DEFINIR_TAXA
        taxa = Decimal('0.03')
        comissao = (valor * taxa).quantize(centavo, rounding=ROUND_HALF_UP)
        bonus_fixo = Decimal('5')
        comissao += bonus_fixo.quantize(centavo, rounding=ROUND_HALF_UP)
        return float(comissao)

    return None
"""


def venda(i, valor, loja=75, marca=10, data="2025-11-01", ignorar=True, taxa_base=0.025):
    return {"id_venda": f"00000000-0000-0000-0000-00000000000{i}", "data_venda": data, "dataVenda": data,
            "valor_venda": valor, "valor": valor, "canal": "PADRAO", "cod_marca": marca, "cod_loja": loja,
            "cod_cargo": 100, "matricula": f"MATRIC-{i}", "taxa_base": taxa_base, "ignorar_vigencia": ignorar}


def payload_simulacao():
    """Como o SimulacaoPythonOrquestradorService monta: 4 itens por venda, contexto por item."""
    itens = []
    for i, valor in ((1, 1200.0), (2, 500.0)):
        for nome, fator in (("100%", 1.0), ("80%", 0.8), ("120%", 1.2), ("150%", 1.5)):
            itens.append({"id": f"v{i}#{nome[:-1]}", "venda": venda(i, round(valor * fator, 2)),
                          "contexto": {"cenario": nome, "fator": fator}})
    itens.append({"id": "v3#100", "venda": venda(3, 900.0, loja=12, marca=20),
                  "contexto": {"cenario": "100%", "fator": 1.0}})
    return {"codigoFonte": PROGRAMA_BACKEND,
            "contexto": {"modo": "SIMULACAO", "campanhaId": 42, "versaoCampanha": 3, "versaoProgramaPython": 2,
                         "competencia": "2025-11"},
            "itens": itens}


class TestExecutarPrograma(unittest.TestCase):
    def setUp(self):
        # Rotas abertas nos testes desta classe (a chave é testada em test_contrato_sprint3).
        self._chave = patch.object(settings, "ai_service_api_key", "")
        self._obrig = patch.object(settings, "ai_inbound_auth_obrigatoria", False)
        self._chave.start()
        self._obrig.start()
        self.client = TestClient(app)

    def tearDown(self):
        self._chave.stop()
        self._obrig.stop()

    def test_programa_do_backend_executa_item_a_item(self):
        r = self.client.post(ROTA, json=payload_simulacao())
        self.assertEqual(r.status_code, 200, r.text)
        corpo = r.json()
        self.assertTrue(corpo["sucesso"])
        self.assertEqual(corpo["motor"], "PYTHON_SANDBOX")
        self.assertEqual(corpo["totalItens"], 9)
        por_id = {x["id"]: x for x in corpo["resultados"]}
        # v1 100%: 1200 × (0,025 + 0,01) = 42,00 (regra 1)
        self.assertEqual(por_id["v1#100"], {"id": "v1#100", "aplicada": True, "comissao": "42.00"})
        # v1 80%: 960 < 1000 -> regra 2: 960 × 0,03 + 5 = 33,80 (a faixa é reavaliada pelo valor escalado)
        self.assertEqual(por_id["v1#80"]["comissao"], "33.80")
        # v2 150%: 750 × 0,03 + 5 = 27,50
        self.assertEqual(por_id["v2#150"]["comissao"], "27.50")
        # v3: nenhuma regra -> aplicada=false, comissao=null (o backend usa a taxa contratual)
        self.assertEqual(por_id["v3#100"], {"id": "v3#100", "aplicada": False, "comissao": None})
        self.assertEqual(corpo["assinaturaPrograma"], hashlib.sha256(PROGRAMA_BACKEND.encode()).hexdigest())
        self.assertEqual(corpo["contexto"]["campanhaId"], 42)
        self.assertIn("X-Correlation-Id", r.headers)

    def test_programa_real_do_gerador_do_backend_com_todas_as_operacoes(self):
        """
        `tests/golden/programa_backend_gerarCodigoConsolidado.py.txt` foi produzido pelo
        `CampanhaProgramaPythonService.gerarCodigoConsolidado` real (6 regras: matrícula, loja com faixa e bônus %,
        cargo com DESCONTO_PONTOS, cargo com DIVISOR_BASE, canal com MULTIPLICADOR_BASE, marca com bônus fixo).
        """
        with open(GOLDEN_PROGRAMA, encoding="utf-8") as f:
            codigo = f.read()

        def v(i, valor, **kw):
            return {**venda(i, valor), **kw}

        casos = [
            ("mat", v(7, 1000.0, matricula="MATRIC-7"), "80.00"),  # 8%
            ("loja", v(1, 1000.0), "40.00"),  # (2,5% + 1 p.p.) + 0,5% de bônus
            ("cargo", v(2, 1000.0, cod_loja=12, cod_cargo=150), "20.00"),  # 2,5% − 0,5 p.p.
            ("div", v(3, 1000.0, cod_loja=12, cod_cargo=160), "12.50"),  # 2,5% ÷ 2
            ("canal", v(4, 1000.0, cod_loja=12, canal="ECOMMERCE"), "37.50"),  # 2,5% × 1,5
            ("marca", v(5, 999.99, cod_loja=75), "35.00"),  # abaixo da faixa da loja: 3% + R$ 5
            ("nada", v(6, 500.0, cod_loja=12, cod_marca=20), None),
            ("fora", v(8, 500.0, data_venda="2025-12-05", ignorar_vigencia=False), None),
        ]
        corpo = {"codigoFonte": codigo, "contexto": {"modo": "SIMULACAO", "campanhaId": 42},
                 "itens": [{"id": i, "venda": d, "contexto": {"cenario": "100%", "fator": 1.0}} for i, d, _ in casos]}
        r = self.client.post(ROTA, json=corpo)
        self.assertEqual(r.status_code, 200, r.text)
        obtido = {x["id"]: x["comissao"] for x in r.json()["resultados"]}
        self.assertEqual(obtido, {i: esperado for i, _, esperado in casos})

    def test_apuracao_respeita_vigencia_e_aceita_itens_sem_contexto(self):
        corpo = {"codigoFonte": PROGRAMA_BACKEND,
                 "contexto": {"modo": "APURACAO", "campanhaId": 42, "versaoCampanha": 3, "versaoProgramaPython": 2,
                              "competencia": "2025-11", "dataInicio": "2025-11-01", "dataFim": "2025-11-30"},
                 "itens": [{"id": "a", "venda": venda(1, 1000.0, ignorar=False)},
                           {"id": "b", "venda": venda(2, 1000.0, data="2025-12-01", ignorar=False)}]}
        r = self.client.post(ROTA, json=corpo)
        self.assertEqual(r.status_code, 200, r.text)
        res = {x["id"]: x for x in r.json()["resultados"]}
        self.assertEqual(res["a"]["comissao"], "35.00")
        self.assertFalse(res["b"]["aplicada"])

    def test_lote_vazio_tem_sucesso(self):
        """O backend chama com lista vazia quando nenhuma venda é calculável; não pode virar erro."""
        r = self.client.post(ROTA, json={"codigoFonte": PROGRAMA_BACKEND, "contexto": {}, "itens": []})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["resultados"], [])
        self.assertEqual(r.json()["totalItens"], 0)

    def test_assinatura_com_contexto(self):
        codigo = ("def calcular_comissao(venda, contexto):\n"
                  "    return float(venda['valor']) * float(contexto.get('fator', 1)) * 0.1\n")
        corpo = {"codigoFonte": codigo, "itens": [{"id": "x", "venda": {"valor": 100.0}, "contexto": {"fator": 2}},
                                                  {"id": "y", "venda": {"valor": 100.0}}]}
        r = self.client.post(ROTA, json=corpo)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([x["comissao"] for x in r.json()["resultados"]], ["20.00", "10.00"])

    def assertFalha(self, r, error_code, erro):
        self.assertEqual(r.status_code, 422, r.text)
        corpo = r.json()
        self.assertFalse(corpo["sucesso"])
        self.assertEqual(corpo["error_code"], error_code)
        self.assertEqual(corpo["erro"], erro)
        self.assertTrue(corpo["detalhe"])
        self.assertEqual(corpo["detail"], corpo["detalhe"])  # o backend lê `detalhe` ou `detail`
        self.assertIsNone(corpo["resultados"])
        return corpo

    def test_codigo_proibido_e_rejeitado_antes_de_executar(self):
        codigo = "import os\n\ndef calcular_comissao(venda):\n    return os.getpid()\n"
        r = self.client.post(ROTA, json={"codigoFonte": codigo, "itens": [{"id": "a", "venda": {}}]})
        corpo = self.assertFalha(r, "PROGRAMA_REJEITADO", "VALIDACAO")
        self.assertTrue(any("os" in v for v in corpo["violacoes"]))

    def test_funcao_ausente_ou_assinatura_errada(self):
        for codigo in ("def simular(vendas, regras, cenario):\n    return {}\n",
                       "def calcular_comissao(*args):\n    return None\n",
                       "def calcular_comissao(a, b, c):\n    return None\n"):
            r = self.client.post(ROTA, json={"codigoFonte": codigo, "itens": []})
            self.assertFalha(r, "PROGRAMA_REJEITADO", "VALIDACAO")

    def test_erro_em_um_item_nao_devolve_resultado_parcial(self):
        codigo = "def calcular_comissao(venda):\n    return 10 / venda['divisor']\n"
        itens = [{"id": "ok", "venda": {"divisor": 2}}, {"id": "quebra", "venda": {"divisor": 0}}]
        corpo = self.assertFalha(self.client.post(ROTA, json={"codigoFonte": codigo, "itens": itens}),
                                 "PROGRAMA_FALHOU", "ERRO_CODIGO")
        self.assertIn("quebra", corpo["detalhe"])
        self.assertIn("ZeroDivisionError", corpo["detalhe"])

    def test_retorno_invalido(self):
        for codigo, trecho in (("def calcular_comissao(venda):\n    return 'dez'\n", "str"),
                               ("def calcular_comissao(venda):\n    return True\n", "bool"),
                               ("def calcular_comissao(venda):\n    return -1.5\n", "negativa")):
            r = self.client.post(ROTA, json={"codigoFonte": codigo, "itens": [{"id": "a", "venda": {}}]})
            corpo = self.assertFalha(r, "PROGRAMA_FALHOU", r.json().get("erro"))
            self.assertIn(trecho, corpo["detalhe"])

    def test_laco_longo_estoura_o_tempo(self):
        codigo = ("def calcular_comissao(venda):\n    t = 0\n    for i in range(10**12):\n        t += i\n"
                  "    return t\n")
        with patch.object(settings, "exec_max_seconds", 1.0):
            r = self.client.post(ROTA, json={"codigoFonte": codigo, "itens": [{"id": "a", "venda": {}}]})
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIn(r.json()["erro"], ("TIMEOUT", "MEMORIA"))

    def test_volume_acima_do_limite(self):
        with patch.object(settings, "exec_max_itens", 2):
            r = self.client.post(ROTA, json={"codigoFonte": PROGRAMA_BACKEND,
                                             "itens": [{"id": str(i), "venda": {}} for i in range(3)]})
        self.assertEqual(r.status_code, 413)
        self.assertEqual(r.json()["error_code"], "VOLUME_EXCEDIDO")

    def test_ids_repetidos_sao_recusados(self):
        r = self.client.post(ROTA, json={"codigoFonte": PROGRAMA_BACKEND,
                                         "itens": [{"id": "a", "venda": {}}, {"id": "a", "venda": {}}]})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error_code"], "VALIDACAO_ENTRADA")

    def test_exige_chave_interna_quando_configurada(self):
        with patch.object(settings, "ai_service_api_key", "segredo"):
            negado = self.client.post(ROTA, json=payload_simulacao())
            aceito = self.client.post(ROTA, json=payload_simulacao(), headers={"X-Internal-Api-Key": "segredo"})
        self.assertEqual(negado.status_code, 401)
        self.assertEqual(aceito.status_code, 200)


class TestValidadorPrograma(unittest.TestCase):
    def test_programa_do_backend_passa_e_simular_continua_igual(self):
        r = validar_programa(PROGRAMA_BACKEND, settings.exec_max_code_lines, settings.exec_max_code_bytes)
        self.assertTrue(r.ok, r.violacoes)
        self.assertEqual(r.aridade, 1)

    def test_comissao_em_decimal_e_quantizada(self):
        from app.core.simulacao import execucao_programa
        from app.schemas.execucao import ExecutarProgramaRequest

        req = ExecutarProgramaRequest(codigoFonte="def calcular_comissao(venda):\n    return 10.005\n",
                                      itens=[{"id": "a", "venda": {}}])
        res = execucao_programa.executar(req)
        self.assertEqual(res.resultados[0].comissao, Decimal("10.01"))


if __name__ == "__main__":
    unittest.main()
