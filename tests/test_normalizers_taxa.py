"""
Testes unitários para o normalizador determinístico de taxa (Task S1-A04).
"""

from decimal import Decimal
import unittest

from app.core.normalizers.taxa import normalizar_taxa


class TestNormalizadorTaxa(unittest.TestCase):
    def test_normalizar_taxa_percentual_padrao(self):
        taxa, pendencias = normalizar_taxa("5%")
        self.assertEqual(taxa, Decimal("0.0500"))
        self.assertEqual(pendencias, [])

    def test_normalizar_taxa_percentual_virgula(self):
        taxa, pendencias = normalizar_taxa("3,5%")
        self.assertEqual(taxa, Decimal("0.0350"))
        self.assertEqual(pendencias, [])

    def test_normalizar_taxa_extenso(self):
        taxa, pendencias = normalizar_taxa("10 por cento")
        self.assertEqual(taxa, Decimal("0.1000"))
        self.assertEqual(pendencias, [])

    def test_normalizar_taxa_decimal_direto(self):
        taxa, pendencias = normalizar_taxa("0.075")
        self.assertEqual(taxa, Decimal("0.0750"))
        self.assertEqual(pendencias, [])

    def test_normalizar_taxa_cem_porcento(self):
        taxa, pendencias = normalizar_taxa("100%")
        self.assertEqual(taxa, Decimal("1.0000"))
        self.assertEqual(pendencias, [])

    def test_normalizar_taxa_invalida_zero_ou_negativa(self):
        taxa, pendencias = normalizar_taxa("0%")
        self.assertIsNone(taxa)
        self.assertEqual(len(pendencias), 1)
        self.assertIn("maior que 0%", pendencias[0])

        taxa_neg, pend_neg = normalizar_taxa("-5%")
        self.assertIsNone(taxa_neg)
        self.assertEqual(len(pend_neg), 1)

    def test_normalizar_taxa_excessiva(self):
        taxa, pendencias = normalizar_taxa("300%")
        self.assertIsNone(taxa)
        self.assertEqual(len(pendencias), 1)
        self.assertIn("excessiva", pendencias[0])

    def test_normalizar_taxa_none_ou_vazio(self):
        taxa, pendencias = normalizar_taxa(None)
        self.assertIsNone(taxa)
        self.assertEqual(len(pendencias), 1)

        taxa_vazio, pend_vazio = normalizar_taxa("")
        self.assertIsNone(taxa_vazio)
        self.assertEqual(len(pend_vazio), 1)


if __name__ == "__main__":
    unittest.main()
