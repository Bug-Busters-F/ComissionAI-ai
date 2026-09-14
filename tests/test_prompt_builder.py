"""
Testes unitários para o montador de prompts (Task S1-A04).
"""

import unittest
from app.core.prompts.regra_prompt import montar_prompt_interpretacao


class TestPromptBuilder(unittest.TestCase):
    def test_montar_prompt_inclui_texto_e_regras(self):
        texto = "Pagar 5% no canal ecommerce durante dezembro"
        contexto = {"ano_referencia": 2026, "canal_padrao": "ECOMMERCE"}

        prompt = montar_prompt_interpretacao(texto=texto, contexto=contexto)

        self.assertIn("DIMENSÕES SUPORTADAS NO MVP", prompt)
        self.assertIn("DIMENSÕES NÃO SUPORTADAS NO MVP", prompt)
        self.assertIn("Pagar 5% no canal ecommerce durante dezembro", prompt)
        self.assertIn("2026", prompt)
        self.assertIn("ECOMMERCE", prompt)
        self.assertIn("Exemplo 1:", prompt)


if __name__ == "__main__":
    unittest.main()
