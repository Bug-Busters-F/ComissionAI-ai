"""
Testes do IA-7 (BUG-120): explicações por cenário com números verificáveis.

Mesma base do IA-5/IA-6: regra p1 = 5% para vendas ≥ 1000 na loja 75; vendas a=1000, b=500 (fallback
contratual de 2,5%) e c (loja 99, fora do público); campanha de 15 dias -> fator 0,5.
"""

import os
import re
import sys
import unittest
from decimal import Decimal
from functools import lru_cache
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
sys.path.insert(0, os.path.dirname(__file__))

from app.core.config import settings  # noqa: E402
from app.schemas.proposta import BlocoProposta, Bonus, Condicoes  # noqa: E402
from test_cenarios_orcamento import QUINZENA, simular, venda  # noqa: E402

D = Decimal
CTX = {"execucaoId": "exec-42"}

# Número em pt-BR: 1.234,56 | 4,58 | 15. Trechos entre aspas (ids das regras) não são números.
_NUMERO = re.compile(r"(?<!\w)(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d+))?(?!\w)")


def numeros_do_texto(texto: str) -> list[Decimal]:
    texto = re.sub(r'"[^"]*"', "", texto)
    return [D(m.group(1).replace(".", "") + ("." + m.group(2) if m.group(2) else "")) for m in _NUMERO.finditer(texto)]


@lru_cache(maxsize=1)
def respostas():
    """Um caso por tipo de explicação (calculado uma vez para o arquivo)."""
    bonus = BlocoProposta(idLocal="p1", condicoes=Condicoes(codLoja=75), taxa=D("0.02"),
                          bonus=Bonus(percentual=D("0.01"), valorFixo=D("50")))
    with patch.object(settings, "calib_max_segundos", 1e-9):
        sem_tempo = simular(orcamento="35", periodoCampanha=QUINZENA, calibrar=True)
    return {
        "sugestao": simular(orcamento="35", periodoCampanha=QUINZENA, calibrar=True, contexto=CTX),
        "sem_solucao": simular(orcamento="5", periodoCampanha=QUINZENA, calibrar=True),
        "sem_orcamento": simular(periodoCampanha=QUINZENA),
        "acima_sem_calibrar": simular(orcamento="35", periodoCampanha=QUINZENA),
        "indisponivel": sem_tempo,
        "bonus": simular(propostas=[bonus], vendas=[venda("a", "1000.00")], orcamento="40", calibrar=True,
                         periodoCampanha={"dataInicio": "2026-12-01", "dataFim": "2026-12-30"}),
        "pendencias": simular(orcamento="35", periodoCampanha=QUINZENA, pendenciasAceitas=[
            {"tipoBase": "VENDAS", "linha": 12, "motivo": "x"}, {"tipoBase": "RH", "linha": 3, "motivo": "y"}]),
    }


class TestNumerosVerificaveis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.casos = respostas()

    def test_todo_numero_do_texto_esta_em_numeros(self):
        """Prova de que o texto não cria números: cada valor citado existe em `numeros` (direto ou em %)."""
        for nome, r in self.casos.items():
            self.assertTrue(r.explicacoes, nome)
            for e in r.explicacoes:
                validos = {abs(v) for v in e.numeros.values()} | {abs(v) * 100 for v in e.numeros.values()}
                for texto in [e.resumo, *e.limitacoes]:
                    for t in numeros_do_texto(texto):
                        with self.subTest(caso=nome, cenario=e.cenario, numero=t):
                            self.assertIn(t, validos, texto)

    def test_numeros_sao_os_valores_calculados(self):
        r = self.casos["sugestao"]
        for e, res, cal in zip(r.explicacoes, r.resultados, r.calibracoes):
            self.assertEqual(e.numeros["custoProjetado"], res.custoProjetado)
            self.assertEqual(e.numeros["custoProposto"], res.totalComissao)
            self.assertEqual(e.numeros["custoContratual"], res.custoContratual)
            self.assertEqual(e.numeros["orcamento"], r.orcamento.orcamentoCampanha)
            if cal.status == "ENQUADRADA":
                self.assertEqual(e.numeros["custoProjetadoRecalculado"], cal.custoProjetadoRecalculado)
                for a in cal.alteracoes:
                    self.assertEqual(e.numeros[f"{a.idLocal}.{a.campo}.antes"], a.antes)
                    self.assertEqual(e.numeros[f"{a.idLocal}.{a.campo}.depois"], a.depois)

    def test_valores_monetarios_formatados_sem_arredondar(self):
        e = self.casos["sugestao"].explicacoes[3]  # 150%: custo projetado 46,88
        self.assertIn("R$ 46,88", e.resumo)
        self.assertIn("R$ 11,88", e.resumo)  # excesso sobre 35


class TestTipos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.casos = respostas()

    def tipos(self, nome):
        return [e.tipo for e in self.casos[nome].explicacoes]

    def test_sugestao_validada_x_dentro_do_orcamento(self):
        self.assertEqual(self.tipos("sugestao"),
                         ["DENTRO_DO_ORCAMENTO", "DENTRO_DO_ORCAMENTO", "SUGESTAO_VALIDADA", "SUGESTAO_VALIDADA"])
        e = self.casos["sugestao"].explicacoes[2]
        self.assertIn("validada por reexecução", e.resumo)
        self.assertIn('taxa da regra "p1" de 5% para 4,58%', e.resumo)

    def test_ausencia_de_solucao_tem_explicacao_propria(self):
        self.assertEqual(set(self.tipos("sem_solucao")), {"SEM_SOLUCAO_VIAVEL"})
        e = self.casos["sem_solucao"].explicacoes[1]
        self.assertIn("Não há alternativa", e.resumo)
        self.assertIn("R$ 6,30", e.resumo)  # custo mínimo
        self.assertIn("taxa contratual", e.resumo)
        self.assertNotIn("validada", e.resumo)

    def test_falha_na_busca_nao_vira_sugestao(self):
        tipos = self.tipos("indisponivel")
        self.assertEqual(tipos[2:], ["SUGESTAO_INDISPONIVEL", "SUGESTAO_INDISPONIVEL"])
        self.assertTrue(all("p1.taxa.depois" not in e.numeros for e in self.casos["indisponivel"].explicacoes))

    def test_acima_sem_calibracao_e_sem_orcamento(self):
        self.assertEqual(self.tipos("acima_sem_calibrar")[2:], ["ACIMA_DO_ORCAMENTO", "ACIMA_DO_ORCAMENTO"])
        self.assertEqual(set(self.tipos("sem_orcamento")), {"SEM_ORCAMENTO"})
        bloqueio = [l for l in self.casos["sem_orcamento"].explicacoes[1].limitacoes if "bloqueado" in l]
        self.assertEqual(bloqueio, ["Encaminhamento ao gerente bloqueado: orçamento monetário não informado."])

    def test_bonus_antes_e_depois(self):
        e = self.casos["bonus"].explicacoes[1]
        self.assertEqual(e.tipo, "SUGESTAO_VALIDADA")
        self.assertIn("bônus fixo da regra \"p1\" de R$ 50,00 para R$ ", e.resumo)
        self.assertIn("bônus percentual da regra \"p1\" de 1% para ", e.resumo)


class TestLimitacoesEFormato(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.casos = respostas()

    def test_ligada_a_execucao_e_ao_cenario(self):
        r = self.casos["sugestao"]
        self.assertEqual([e.cenario for e in r.explicacoes], [x.cenario for x in r.resultados])
        self.assertEqual([e.multiplicadorVendas for e in r.explicacoes], [D("0.8"), D("1"), D("1.2"), D("1.5")])
        self.assertTrue(all(e.execucaoId == "exec-42" for e in r.explicacoes))
        self.assertTrue(all(e.assinaturaPrograma == r.assinaturaPrograma for e in r.explicacoes))
        self.assertTrue(all(e.execucaoId is None for e in self.casos["sem_orcamento"].explicacoes))

    def test_limitacoes(self):
        lim = self.casos["sugestao"].explicacoes[0].limitacoes  # 80%: a venda "a" sai da faixa da p1
        texto = " ".join(lim)
        self.assertIn("2 venda(s) do público sem regra aplicável", texto)
        self.assertIn("1 venda(s) mudam de faixa", texto)
        self.assertIn("1 venda(s) fora do público", texto)
        self.assertIn("15 dia(s)", texto)
        self.assertEqual(lim[-1], "Resultado de simulação; não substitui a apuração oficial.")

    def test_pendencias_aceitas_viram_limitacao(self):
        lim = self.casos["pendencias"].explicacoes[1].limitacoes
        self.assertTrue(any("2 pendência(s) de base aceita(s)" in l for l in lim))

    def test_deterministico(self):
        r2 = simular(orcamento="35", periodoCampanha=QUINZENA, calibrar=True, contexto=CTX)
        self.assertEqual([e.model_dump() for e in r2.explicacoes],
                         [e.model_dump() for e in self.casos["sugestao"].explicacoes])

    def test_sem_numeros_sem_explicacao(self):
        r = simular(vendas=[venda("c", "800.00", loja=99)], orcamento="35")
        self.assertEqual((r.resultados, r.explicacoes), ([], []))


if __name__ == "__main__":
    unittest.main()
