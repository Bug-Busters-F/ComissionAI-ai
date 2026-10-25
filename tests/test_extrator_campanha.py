"""Testes da extração multi-regra (IA-2): exemplos de interpretação com LLM mockado."""

import os
import sys
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from app.core.normalizers.faixas import normalizar_faixa, normalizar_valor_monetario
from app.core.services.campanha import ExtratorCampanha, localizar_trecho, normalizar_matricula
from app.schemas.proposta import InterpretarRequestV2

CATALOGO = {
    "marcas": {"10": "PRETO", "20": "BRANCO"},
    "cargos": {"100": "VENDEDOR LOJA", "150": "GERENTE DE LOJA", "151": "GERENTE QUIOSQUE"},
    "canais": ["ECOMMERCE", "LOJA_FISICA"],
}


def extrair(texto, saida_llm, **req):
    provider = MagicMock()
    provider.complete.return_value = saida_llm
    request = InterpretarRequestV2(texto=texto, dataReferencia=date(2026, 9, 7), catalogo=CATALOGO, **req)
    return ExtratorCampanha(provider).extrair(request)


def codigos(bloco):
    return {p.codigo.value for p in bloco.bloco.pendencias}


class TestMultiplasRegras(unittest.TestCase):
    def test_duas_regras_com_origem_e_vigencia_herdada(self):
        texto = "3% para vendedores da loja 75 e 2% para gerentes da loja 75 em dezembro"
        r = extrair(texto, {
            "regras": [
                {"trecho_origem": "3% para vendedores da loja 75", "taxa_raw": "3%", "cargo_raw": "vendedores", "loja_raw": "75"},
                {"trecho_origem": "2% para gerentes da loja 75", "taxa_raw": "2%", "cargo_raw": "gerentes", "loja_raw": "75"},
            ],
            "vigencia_inicio_raw": "dezembro", "vigencia_fim_raw": "dezembro",
        })
        self.assertEqual(len(r.blocos), 2)
        b1, b2 = (b.bloco for b in r.blocos)
        self.assertEqual((b1.taxa, b1.condicoes.codCargo, b1.condicoes.codLoja), (Decimal("0.0300"), 100, 75))
        self.assertEqual(b1.origem.trecho, "3% para vendedores da loja 75")
        self.assertEqual(texto[b1.origem.inicio:b1.origem.fim], b1.origem.trecho)
        self.assertEqual((b1.dataInicio, b1.dataFim), (date(2026, 12, 1), date(2026, 12, 31)))
        self.assertEqual((b2.dataInicio, b2.dataFim), (b1.dataInicio, b1.dataFim))
        # 'gerentes' é ambíguo entre dois cargos com códigos distintos: pendência, sem escolher
        self.assertIn("AMBIGUIDADE_CARGO", codigos(r.blocos[1]))
        self.assertIsNone(b2.condicoes.codCargo)
        self.assertIn("cargo", r.blocos[1].lacunas_cadastro)
        self.assertEqual(r.trechos_nao_mapeados, [])

    def test_faixas_contiguas(self):
        r = extrair("2% nas vendas até R$ 10 mil e 3% nas vendas acima de R$ 10 mil no ecommerce", {
            "regras": [
                {"trecho_origem": "2% nas vendas até R$ 10 mil", "taxa_raw": "2%", "canal": "ECOMMERCE",
                 "faixa_max_raw": "R$ 10 mil", "faixa_max_inclusivo": True},
                {"trecho_origem": "3% nas vendas acima de R$ 10 mil", "taxa_raw": "3%", "canal": "ECOMMERCE",
                 "faixa_min_raw": "R$ 10 mil", "faixa_min_inclusivo": False},
            ],
            "vigencia_inicio_raw": "dezembro", "vigencia_fim_raw": "dezembro",
        })
        f1, f2 = (b.bloco.condicoes.faixaValor for b in r.blocos)
        self.assertEqual((f1.max, f1.maxInclusivo, f1.min), (Decimal("10000.00"), True, None))
        self.assertEqual((f2.min, f2.minInclusivo, f2.max), (Decimal("10000.00"), False, None))

    def test_individual_com_bonus_valor_fixo(self):
        r = extrair("A matrícula MATRIC-56 ganha 6% mais um bônus de R$ 200 por venda em outubro de 2026", {
            "regras": [{"trecho_origem": "A matrícula MATRIC-56 ganha 6% mais um bônus de R$ 200 por venda",
                        "matricula_raw": "MATRIC-56", "taxa_raw": "6%", "bonus_valor_raw": "R$ 200"}],
            "vigencia_inicio_raw": "outubro de 2026", "vigencia_fim_raw": "outubro de 2026",
        })
        b = r.blocos[0].bloco
        self.assertEqual(b.condicoes.matricula, "MATRIC-56")
        self.assertEqual(b.bonus.valorFixo, Decimal("200.00"))
        self.assertIsNone(b.bonus.percentual)
        self.assertGreater(b.confianca, Decimal("0.5"))

    def test_parcialmente_mensuravel_nao_descarta(self):
        texto = "5% para quem bater a meta da loja 12. Os gerentes também ganham."
        r = extrair(texto, {
            "regras": [
                {"trecho_origem": "5% para quem bater a meta da loja 12", "taxa_raw": "5%", "loja_raw": "12",
                 "criterios_nao_suportados": ["meta de faturamento"]},
                {"trecho_origem": "Os gerentes também ganham", "cargo_raw": "gerentes"},
            ],
            "vigencia_inicio_raw": "dezembro",
        })
        self.assertEqual(len(r.blocos), 2)
        self.assertIn("CRITERIO_NAO_SUPORTADO", codigos(r.blocos[0]))
        self.assertEqual(r.blocos[0].bloco.taxa, Decimal("0.0500"))  # a regra é preservada
        self.assertIn("CAMPO_AUSENTE", codigos(r.blocos[1]))
        self.assertIsNone(r.blocos[1].bloco.taxa)

    def test_ajuste_sobre_base_nao_vira_taxa(self):
        r = extrair("Vendedores da marca PRETO ganham mais 1 ponto percentual sobre a base em novembro", {
            "regras": [{"trecho_origem": "Vendedores da marca PRETO ganham mais 1 ponto percentual sobre a base",
                        "cargo_raw": "Vendedores", "marca_raw": "PRETO", "operacao_raw": "mais 1 ponto percentual"}],
            "vigencia_inicio_raw": "novembro", "vigencia_fim_raw": "novembro",
        })
        b = r.blocos[0].bloco
        self.assertIsNone(b.taxa)
        self.assertIsNone(b.operacao)
        self.assertEqual(b.condicoes.codMarca, 10)
        self.assertIn("CAMPO_AUSENTE", codigos(r.blocos[0]))


class TestVigenciaEOrigem(unittest.TestCase):
    def test_periodo_da_regra_diferente_da_campanha(self):
        from app.schemas.proposta import VigenciaCampanha

        r = extrair("3% para vendedores em janeiro", {
            "regras": [{"trecho_origem": "3% para vendedores em janeiro", "taxa_raw": "3%",
                        "cargo_raw": "vendedores", "vigencia_inicio_raw": "janeiro", "vigencia_fim_raw": "janeiro"}],
        }, vigenciaCampanha=VigenciaCampanha(inicio=date(2026, 12, 1), fim=date(2026, 12, 31)))
        b = r.blocos[0].bloco
        self.assertEqual((b.dataInicio, b.dataFim), (date(2026, 12, 1), date(2026, 12, 31)))  # herdou
        self.assertIn("VIGENCIA_INCOMPATIVEL", codigos(r.blocos[0]))

    def test_regras_com_periodos_diferentes_sem_vigencia_comum(self):
        r = extrair("3% para vendedores em janeiro e 2% para gerentes em fevereiro", {
            "regras": [
                {"trecho_origem": "3% para vendedores em janeiro", "taxa_raw": "3%", "vigencia_inicio_raw": "janeiro", "vigencia_fim_raw": "janeiro"},
                {"trecho_origem": "2% para gerentes em fevereiro", "taxa_raw": "2%", "vigencia_inicio_raw": "fevereiro", "vigencia_fim_raw": "fevereiro"},
            ],
        })
        for b in r.blocos:
            self.assertIn("VIGENCIA_INCOMPATIVEL", codigos(b))

    def test_trecho_alucinado_e_descartado_com_pendencia(self):
        r = extrair("3% para vendedores", {
            "regras": [{"trecho_origem": "5% para a lua", "taxa_raw": "3%"}], "vigencia_inicio_raw": "dezembro",
        })
        self.assertIsNone(r.blocos[0].bloco.origem)
        self.assertIn("TRECHO_INCOMPLETO", codigos(r.blocos[0]))

    def test_texto_nao_coberto_vira_trecho_nao_mapeado(self):
        texto = "3% para vendedores da loja 75 em dezembro. Pagar tambem pelos produtos da categoria calcados"
        r = extrair(texto, {
            "regras": [{"trecho_origem": "3% para vendedores da loja 75 em dezembro", "taxa_raw": "3%", "loja_raw": "75"}],
            "vigencia_inicio_raw": "dezembro",
        })
        self.assertEqual(len(r.trechos_nao_mapeados), 1)
        self.assertIn("categoria calcados", r.trechos_nao_mapeados[0].trecho)

    def test_nao_mapeado_declarado_pelo_modelo_e_validado(self):
        r = extrair("3% para vendedores. blablabla incompleto aqui", {
            "regras": [{"trecho_origem": "3% para vendedores", "taxa_raw": "3%"}],
            "trechos_nao_mapeados": ["blablabla incompleto aqui", "texto inexistente"],
            "vigencia_inicio_raw": "dezembro",
        })
        self.assertEqual([t.trecho for t in r.trechos_nao_mapeados], ["blablabla incompleto aqui"])

    def test_loja_fora_do_catalogo_de_lojas(self):
        provider = MagicMock()
        provider.complete.return_value = {
            "regras": [{"trecho_origem": "3% loja 999", "taxa_raw": "3%", "loja_raw": "999"}],
            "vigencia_inicio_raw": "dezembro",
        }
        req = InterpretarRequestV2(texto="3% loja 999", dataReferencia=date(2026, 9, 7),
                                   catalogo={**CATALOGO, "lojas": {"75": "A"}})
        r = ExtratorCampanha(provider).extrair(req)
        self.assertIn("CADASTRO_INEXISTENTE", codigos(r.blocos[0]))
        self.assertIsNone(r.blocos[0].bloco.condicoes.codLoja)


class TestNormalizadoresNovos(unittest.TestCase):
    def test_valores(self):
        casos = {"R$ 1.500,00": "1500.00", "10 mil": "10000.00", "10k": "10000.00", "1,5 milhão": "1500000.00", "10.000": "10000.00"}
        for raw, esperado in casos.items():
            self.assertEqual(normalizar_valor_monetario(raw)[0], Decimal(esperado), raw)
        self.assertIsNone(normalizar_valor_monetario("muito dinheiro")[0])

    def test_faixa_invertida_gera_pendencia(self):
        faixa, pend = normalizar_faixa("20 mil", "10 mil")
        self.assertIsNone(faixa)
        self.assertTrue(pend)

    def test_matricula(self):
        self.assertEqual(normalizar_matricula(" matric-56 ")[0], "MATRIC-56")
        self.assertIsNone(normalizar_matricula("@@")[0])

    def test_localizar_trecho_tolera_caixa_e_espacos(self):
        self.assertEqual(localizar_trecho("Pagar  3% PARA vendedores", "pagar 3% para vendedores"), (0, 25))
        self.assertIsNone(localizar_trecho("abc", "xyz"))


if __name__ == "__main__":
    unittest.main()
