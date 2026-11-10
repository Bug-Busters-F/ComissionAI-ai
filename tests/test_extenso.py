import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from app.core.normalizers.extenso import numero_por_extenso


class TestNumeroPorExtenso(unittest.TestCase):
    def test_unidade_simples(self):
        self.assertEqual(numero_por_extenso("dez"), Decimal(10))

    def test_dezena_composta(self):
        self.assertEqual(numero_por_extenso("vinte e cinco"), Decimal(25))

    def test_centena_composta(self):
        self.assertEqual(numero_por_extenso("cento e vinte"), Decimal(120))

    def test_mil_simples(self):
        self.assertEqual(numero_por_extenso("cinco mil"), Decimal(5000))

    def test_mil_e_centena(self):
        self.assertEqual(numero_por_extenso("mil e quinhentos"), Decimal(1500))

    def test_milhao(self):
        self.assertEqual(numero_por_extenso("um milhão e duzentos mil"), Decimal(1_200_000))

    def test_ignora_palavras_de_contexto(self):
        self.assertEqual(numero_por_extenso("cinco mil reais"), Decimal(5000))

    def test_texto_vazio_retorna_none(self):
        self.assertIsNone(numero_por_extenso(""))
        self.assertIsNone(numero_por_extenso(None))

    def test_palavra_desconhecida_nao_arrisca_palpite(self):
        self.assertIsNone(numero_por_extenso("vendedores da loja"))

    def test_numero_digito_nao_e_aceito_aqui(self):
        # dígitos não são vocabulário de extenso; quem decide usar este fallback é o chamador
        self.assertIsNone(numero_por_extenso("10 mil"))


if __name__ == "__main__":
    unittest.main()
