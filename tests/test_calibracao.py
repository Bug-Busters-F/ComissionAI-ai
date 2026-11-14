"""
Testes do IA-6 (BUG-119): calibração verificável por cenário excedido.

Base dos números (mesma do IA-5): regra p1 = 5% para vendas ≥ 1000 na loja 75; vendas a=1000 e b=500
(b fica no fallback contratual de 2,5%); campanha de 15 dias -> fator 0,5.
Custo projetado: 80% = 15,00 | 100% = 31,25 | 120% = 37,50 | 150% = 46,88.
"""

import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
sys.path.insert(0, os.path.dirname(__file__))

from app.core.simulacao.calibracao import Avaliacao, Calibrador, aplicar_fator  # noqa: E402
from app.schemas.proposta import BlocoProposta, Bonus, Cenario, Condicoes, ResultadoCenario  # noqa: E402
from test_cenarios_orcamento import P1, QUINZENA, VENDAS, regra, simular, venda  # noqa: E402

D = Decimal


def aplicar(propostas, calibracao):
    """O que o usuário faria no rascunho: aplica as alterações estruturadas da alternativa."""
    por_id = {p.idLocal: p for p in propostas}
    for a in calibracao.alteracoes:
        p = por_id[a.idLocal]
        if a.campo == "taxa":
            por_id[a.idLocal] = p.model_copy(update={"taxa": a.depois})
        else:
            chave = a.campo.split(".")[1]
            por_id[a.idLocal] = p.model_copy(update={"bonus": p.bonus.model_copy(update={chave: a.depois})})
    return [por_id[p.idLocal] for p in propostas]


class TestCalibracaoPorCenario(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = simular(orcamento="35", periodoCampanha=QUINZENA, calibrar=True)
        cls.cal = {c.multiplicadorVendas: c for c in cls.r.calibracoes}

    def test_uma_entrada_por_cenario(self):
        self.assertEqual(self.r.statusSugestoes, "OK")
        self.assertEqual([c.status for c in self.r.calibracoes],
                         ["NAO_NECESSARIA", "NAO_NECESSARIA", "ENQUADRADA", "ENQUADRADA"])

    def test_alternativa_enquadrada_por_reexecucao(self):
        c = self.cal[D("1.2")]
        self.assertLessEqual(c.custoProjetadoRecalculado, D("35"))
        self.assertEqual(c.folga, D("35") - c.custoProjetadoRecalculado)
        self.assertEqual([(a.idLocal, a.campo, a.antes) for a in c.alteracoes], [("p1", "taxa", D("0.05"))])
        self.assertLess(c.alteracoes[0].depois, D("0.05"))
        self.assertLessEqual(c.tentativas, 12)

    def test_alternativas_sao_independentes(self):
        """150% exige corte maior que 120%: cada cenário recebe a sua própria alternativa."""
        self.assertLess(self.cal[D("1.5")].alteracoes[0].depois, self.cal[D("1.2")].alteracoes[0].depois)

    def test_alternativa_e_a_mais_proxima_da_proposta_que_cabe(self):
        # 120%: (1200 × t + 600 × 2,5%) × 0,5 ≤ 35  ->  t ≤ 0,04583; a busca para a menos de 0,0002 do limite
        t = self.cal[D("1.2")].alteracoes[0].depois
        self.assertGreater(t, D("0.0456"))
        self.assertLessEqual(t, D("0.0458"))

    def test_aplicar_a_alternativa_reproduz_o_custo_informado(self):
        """Verificabilidade: nova simulação com os parâmetros sugeridos dá exatamente o custo devolvido."""
        for mult in (D("1.2"), D("1.5")):
            c = self.cal[mult]
            nova = simular(propostas=aplicar([P1], c), orcamento="35", periodoCampanha=QUINZENA)
            res = next(x for x in nova.resultados if x.multiplicadorVendas == mult)
            self.assertEqual(res.custoProjetado, c.custoProjetadoRecalculado)
            self.assertEqual(res.enquadramento.statusEnquadramento, "ENQUADRADO")

    def test_orcamento_preservado(self):
        self.assertTrue(all(c.orcamento == D("35") for c in self.r.calibracoes))
        self.assertEqual(self.r.orcamento.orcamentoCampanha, D("35"))
        self.assertEqual(self.r.resultados[2].custoProjetado, D("37.50"))  # números da simulação intactos

    def test_assinatura_do_programa_executado(self):
        self.assertTrue(all(c.assinaturaPrograma == self.r.assinaturaPrograma for c in self.r.calibracoes))

    def test_deterministico(self):
        r2 = simular(orcamento="35", periodoCampanha=QUINZENA, calibrar=True)
        self.assertEqual([c.model_dump() for c in r2.calibracoes], [c.model_dump() for c in self.r.calibracoes])


class TestSemSolucao(unittest.TestCase):
    def test_parcela_contratual_acima_do_teto(self):
        # mínimo em 100%: (1000 × 0,0001 + 500 × 2,5%) × 0,5 = 6,30 > 5
        r = simular(orcamento="5", periodoCampanha=QUINZENA, calibrar=True)
        c = r.calibracoes[1]
        self.assertEqual(c.status, "SEM_SOLUCAO_VIAVEL")
        self.assertEqual(c.custoProjetadoMinimo, D("6.30"))
        self.assertEqual(c.alteracoes, [])
        self.assertIn("taxa contratual", c.motivo)
        self.assertEqual(r.statusSugestoes, "OK")  # resposta válida: não há alternativa possível


class TestBonus(unittest.TestCase):
    def test_bonus_percentual_e_fixo_tambem_sao_ajustados(self):
        p = BlocoProposta(idLocal="p1", condicoes=Condicoes(codLoja=75), taxa=D("0.02"),
                          bonus=Bonus(percentual=D("0.01"), valorFixo=D("50")))
        r = simular(propostas=[p], vendas=[venda("a", "1000.00")], orcamento="40", calibrar=True,
                    periodoCampanha={"dataInicio": "2026-12-01", "dataFim": "2026-12-30"})
        c = r.calibracoes[1]  # 100%: 20 + 10 + 50 = 80 > 40
        self.assertEqual(c.status, "ENQUADRADA")
        self.assertEqual({a.campo for a in c.alteracoes}, {"taxa", "bonus.percentual", "bonus.valorFixo"})
        nova = simular(propostas=aplicar([p], c), vendas=[venda("a", "1000.00")], orcamento="40",
                       periodoCampanha={"dataInicio": "2026-12-01", "dataFim": "2026-12-30"})
        self.assertEqual(nova.resultados[1].custoProjetado, c.custoProjetadoRecalculado)


class TestFalhas(unittest.TestCase):
    def test_sem_orcamento_nao_inventa_sugestao(self):
        r = simular(periodoCampanha=QUINZENA, calibrar=True)
        self.assertEqual((r.calibracoes, r.statusSugestoes), ([], "FALHA"))
        self.assertTrue(any(p.campo == "orcamento" for p in r.pendencias))
        self.assertEqual(len(r.resultados), 4)  # a simulação continua válida

    def test_nao_solicitada(self):
        r = simular(orcamento="35", periodoCampanha=QUINZENA)
        self.assertEqual((r.calibracoes, r.statusSugestoes), ([], "NAO_SOLICITADA"))

    def excedido(self):
        return ResultadoCenario(cenario="x", totalVendas=D("100"), totalComissao=D("100"), custoProjetado=D("100"))

    def test_reexecucao_falha_vira_falha_sem_alteracoes(self):
        cal = Calibrador(lambda b, c: Avaliacao(None, "TIMEOUT: excedeu"), 12, 20)
        c = cal.calibrar([P1], self.excedido(), Cenario(nome="x"), D("50"), "abc")
        self.assertEqual((c.status, c.alteracoes), ("FALHA", []))
        self.assertIn("TIMEOUT", c.motivo)

    def test_limite_de_tempo(self):
        tempos = iter([0.0, 999.0])  # início; o tempo estoura antes da primeira alternativa
        piso = ResultadoCenario(cenario="x", totalVendas=D("1"), totalComissao=D("1"), custoProjetado=D("1"))
        cal = Calibrador(lambda b, c: Avaliacao(piso), 12, 20, relogio=lambda: next(tempos))
        c = cal.calibrar([P1], self.excedido(), Cenario(nome="x"), D("50"), "abc")
        self.assertEqual(c.status, "FALHA")
        self.assertIn("Limite", c.motivo)
        self.assertEqual(c.tentativas, 1)

    def test_tempo_e_compartilhado_entre_cenarios(self):
        """O orçamento de tempo é da requisição: o 2º cenário não ganha outros 20 s."""
        tempos = iter([0.0, 5.0, 999.0])  # criação; laço do 1º cenário; laço do 2º cenário
        barato = ResultadoCenario(cenario="x", totalVendas=D("1"), totalComissao=D("1"), custoProjetado=D("1"))
        cal = Calibrador(lambda b, c: Avaliacao(barato), 2, 20, relogio=lambda: next(tempos))
        primeiro = cal.calibrar([P1], self.excedido(), Cenario(nome="a"), D("50"), "abc")
        segundo = cal.calibrar([P1], self.excedido(), Cenario(nome="b"), D("50"), "abc")
        self.assertEqual((primeiro.status, segundo.status), ("ENQUADRADA", "FALHA"))

    def test_limite_de_tentativas_respeitado(self):
        chamadas = []

        def avaliar(blocos, cen):
            chamadas.append(blocos[0].taxa)
            custo = blocos[0].taxa * 1000  # λ=1 -> 50; teto 30 -> λ ≤ 0,6
            return Avaliacao(ResultadoCenario(cenario="x", totalVendas=D("1"), totalComissao=custo,
                                              custoProjetado=custo))

        c = Calibrador(avaliar, 4, 20).calibrar([P1], self.excedido(), Cenario(nome="x"), D("30"), "abc")
        self.assertEqual(len(chamadas), 4)
        self.assertEqual(c.status, "ENQUADRADA")
        self.assertLessEqual(c.custoProjetadoRecalculado, D("30"))


class TestAplicarFator(unittest.TestCase):
    def test_piso_nunca_zera_parametros(self):
        p = BlocoProposta(idLocal="p", taxa=D("0.02"), bonus=Bonus(valorFixo=D("10")))
        piso = aplicar_fator([p], None)[0]
        self.assertEqual((piso.taxa, piso.bonus.valorFixo, piso.bonus.percentual), (D("0.0001"), D("0.01"), None))
        self.assertEqual(aplicar_fator([p], D("0.5"))[0].taxa, D("0.0100"))


if __name__ == "__main__":
    unittest.main()
