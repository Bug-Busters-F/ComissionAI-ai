"""
Testes unitários para o cálculo determinístico de confiança (Task S1-A04).
"""

from datetime import date
from decimal import Decimal
import unittest

from app.core.normalizers.confianca import calcular_confianca


class TestNormalizadorConfianca(unittest.TestCase):
    def test_calcular_confianca_perfeita(self):
        conf = calcular_confianca(
            taxa=Decimal("0.0500"),
            canal="ECOMMERCE",
            data_inicio=date(2026, 12, 1),
            data_fim=date(2026, 12, 31),
            criterios_nao_suportados=[],
            ambiguidades=[],
            pendencias_normalizacao=[],
        )
        self.assertEqual(conf, Decimal("1.00"))

    def test_calcular_confianca_sem_data_fim_mas_completa(self):
        conf = calcular_confianca(
            taxa=Decimal("0.0500"),
            canal="ECOMMERCE",
            data_inicio=date(2026, 10, 1),
            data_fim=None,
            criterios_nao_suportados=[],
            ambiguidades=[],
            pendencias_normalizacao=[],
        )
        self.assertEqual(conf, Decimal("1.00"))

    def test_calcular_confianca_com_criterios_nao_suportados(self):
        conf = calcular_confianca(
            taxa=Decimal("0.0500"),
            canal="ECOMMERCE",
            data_inicio=date(2026, 12, 1),
            data_fim=date(2026, 12, 31),
            criterios_nao_suportados=["loja 75", "marca PRETO"],
            ambiguidades=[],
            pendencias_normalizacao=[],
        )
        # 1.00 - 0.20*2 = 0.60
        self.assertEqual(conf, Decimal("0.60"))

    def test_calcular_confianca_campos_ausentes(self):
        conf = calcular_confianca(
            taxa=None,
            canal=None,
            data_inicio=None,
            data_fim=None,
            criterios_nao_suportados=[],
            ambiguidades=["Canal não informado", "Taxa não informada"],
            pendencias_normalizacao=["Data não identificada"],
        )
        # 0.00 base - penalizações -> limitado a 0.00
        self.assertEqual(conf, Decimal("0.00"))


if __name__ == "__main__":
    unittest.main()
