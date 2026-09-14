"""
Testes unitários para o normalizador de canais (Task S1-A04).
"""

import unittest
from app.core.normalizers.canais import normalizar_canal


class TestNormalizadorCanais(unittest.TestCase):
    def test_normalizar_canal_direto(self):
        canal, pendencias = normalizar_canal("ECOMMERCE")
        self.assertEqual(canal, "ECOMMERCE")
        self.assertEqual(pendencias, [])

    def test_normalizar_canal_minusculo_e_espacos(self):
        canal, pendencias = normalizar_canal("  ecommerce  ")
        self.assertEqual(canal, "ECOMMERCE")
        self.assertEqual(pendencias, [])

    def test_normalizar_canal_sinonimos(self):
        canal_wpp, pend_wpp = normalizar_canal("zap")
        self.assertEqual(canal_wpp, "WHATSAPP")
        self.assertEqual(pend_wpp, [])

        canal_loja, pend_loja = normalizar_canal("loja física")
        self.assertEqual(canal_loja, "LOJA_FISICA")
        self.assertEqual(pend_loja, [])

    def test_normalizar_canal_com_canal_padrao_no_contexto(self):
        canal, pendencias = normalizar_canal(None, {"canal_padrao": "ECOMMERCE"})
        self.assertEqual(canal, "ECOMMERCE")
        self.assertEqual(pendencias, [])

    def test_normalizar_canal_invalido(self):
        canal, pendencias = normalizar_canal("CANAL_DESCONHECIDO_XYZ")
        self.assertIsNone(canal)
        self.assertEqual(len(pendencias), 1)
        self.assertIn("não é reconhecido", pendencias[0])

    def test_normalizar_canal_ausente_sem_contexto(self):
        canal, pendencias = normalizar_canal(None, {})
        self.assertIsNone(canal)
        self.assertEqual(len(pendencias), 1)
        self.assertIn("não identificado", pendencias[0])


if __name__ == "__main__":
    unittest.main()
