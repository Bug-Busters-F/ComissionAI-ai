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
        self.assertEqual(pendencias, [])

    def test_dicionario_dimensoes_canais_tem_prioridade(self):
        """Canal no dicionario_dimensoes tem prioridade sobre lista interna MVP."""
        contexto = {
            "dicionario_dimensoes": {
                "canais": ["LOJA_FISICA", "ECOMMERCE", "APP"],
            }
        }
        canal, pendencias = normalizar_canal("APP", contexto)
        self.assertEqual(canal, "APP")
        self.assertEqual(pendencias, [])

    def test_dicionario_dimensoes_canais_rejeita_canal_fora_do_catalogo(self):
        """Canal fora do catálogo enviado deve gerar pendência mesmo que seja padrão MVP."""
        contexto = {
            "dicionario_dimensoes": {
                "canais": ["LOJA_FISICA"],  # catálogo restrito enviado pelo backend
            }
        }
        canal, pendencias = normalizar_canal("ECOMMERCE", contexto)
        self.assertIsNone(canal)
        self.assertEqual(len(pendencias), 1)

    def test_dicionario_dimensoes_sem_canais_usa_fallback(self):
        """Se dicionario_dimensoes não tem 'canais', usa fallback legado."""
        contexto = {
            "dicionario_dimensoes": {
                "marcas": {"10": "PRETO"},
            }
        }
        canal, pendencias = normalizar_canal("ECOMMERCE", contexto)
        self.assertEqual(canal, "ECOMMERCE")
        self.assertEqual(pendencias, [])


if __name__ == "__main__":
    unittest.main()
