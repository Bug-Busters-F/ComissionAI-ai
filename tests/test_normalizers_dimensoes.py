"""
Testes unitários para o normalizador de dimensões de negócio: marca, loja e cargo.
(Task S1-A04 — normalizers/dimensoes.py)
"""

import unittest

from app.core.normalizers.dimensoes import normalizar_cargo, normalizar_loja, normalizar_marca


CATALOGO_COMPLETO = {
    "dicionario_dimensoes": {
        "marcas": {
            "10": "PRETO",
            "20": "BRANCO",
            "30": "AZUL",
            "40": "VERMELHO",
            "50": "AMARELO",
            "60": "CINZA",
        },
        "cargos": {
            "100": "VENDEDOR LOJA",
            "150": "GERENTE DE LOJA",
            "151": "GERENTE QUIOSQUE",
            "200": "VENDEDOR BALCAO",
            "300": "ASSISTENTE DE VENDAS",
        },
        "canais": ["LOJA_FISICA", "ECOMMERCE", "BALCAO", "WHATSAPP"],
    }
}


# ---------------------------------------------------------------------------
# Normalização de Marca
# ---------------------------------------------------------------------------

class TestNormalizarMarca(unittest.TestCase):

    def test_marca_encontrada_exatamente(self):
        cod, nome, pends = normalizar_marca("PRETO", CATALOGO_COMPLETO)
        self.assertEqual(cod, 10)
        self.assertEqual(nome, "PRETO")
        self.assertEqual(pends, [])

    def test_marca_encontrada_minusculas(self):
        cod, nome, pends = normalizar_marca("preto", CATALOGO_COMPLETO)
        self.assertEqual(cod, 10)
        self.assertEqual(nome, "PRETO")
        self.assertEqual(pends, [])

    def test_marca_com_prefixo_marca(self):
        """Expressão 'marca BRANCO' deve resolver para BRANCO."""
        cod, nome, pends = normalizar_marca("marca BRANCO", CATALOGO_COMPLETO)
        self.assertEqual(cod, 20)
        self.assertEqual(nome, "BRANCO")
        self.assertEqual(pends, [])

    def test_marca_com_acento(self):
        """Nomes com acento no texto devem ser normalizados."""
        # Simula catálogo com acento
        contexto = {"dicionario_dimensoes": {"marcas": {"99": "AZUL"}, "cargos": {}, "canais": []}}
        cod, nome, pends = normalizar_marca("Azul", contexto)
        self.assertEqual(cod, 99)
        self.assertEqual(nome, "AZUL")

    def test_marca_nao_encontrada_gera_pendencia(self):
        cod, nome, pends = normalizar_marca("VERDE", CATALOGO_COMPLETO)
        self.assertIsNone(cod)
        self.assertIsNone(nome)
        self.assertEqual(len(pends), 1)
        self.assertIn("VERDE", pends[0])

    def test_marca_none_retorna_null_sem_pendencia(self):
        cod, nome, pends = normalizar_marca(None, CATALOGO_COMPLETO)
        self.assertIsNone(cod)
        self.assertIsNone(nome)
        self.assertEqual(pends, [])

    def test_marca_vazia_retorna_null_sem_pendencia(self):
        cod, nome, pends = normalizar_marca("  ", CATALOGO_COMPLETO)
        self.assertIsNone(cod)
        self.assertIsNone(nome)
        self.assertEqual(pends, [])

    def test_sem_catalogo_retorna_null_sem_pendencia(self):
        """Sem catálogo não é possível resolver — retorna null sem pendência."""
        cod, nome, pends = normalizar_marca("PRETO", {})
        self.assertIsNone(cod)
        self.assertIsNone(nome)
        self.assertEqual(pends, [])

    def test_sem_contexto_retorna_null_sem_pendencia(self):
        cod, nome, pends = normalizar_marca("PRETO", None)
        self.assertIsNone(cod)
        self.assertIsNone(nome)
        self.assertEqual(pends, [])


# ---------------------------------------------------------------------------
# Normalização de Loja
# ---------------------------------------------------------------------------

class TestNormalizarLoja(unittest.TestCase):

    def test_loja_codigo_numerico_puro(self):
        cod, pends = normalizar_loja("75")
        self.assertEqual(cod, 75)
        self.assertEqual(pends, [])

    def test_loja_expressao_loja_numero(self):
        cod, pends = normalizar_loja("loja 75")
        self.assertEqual(cod, 75)
        self.assertEqual(pends, [])

    def test_loja_expressao_loja_numero_35(self):
        cod, pends = normalizar_loja("loja 35")
        self.assertEqual(cod, 35)
        self.assertEqual(pends, [])

    def test_loja_none_retorna_null_sem_pendencia(self):
        cod, pends = normalizar_loja(None)
        self.assertIsNone(cod)
        self.assertEqual(pends, [])

    def test_loja_vazia_retorna_null_sem_pendencia(self):
        cod, pends = normalizar_loja("  ")
        self.assertIsNone(cod)
        self.assertEqual(pends, [])

    def test_loja_sem_numero_gera_pendencia(self):
        cod, pends = normalizar_loja("loja do centro")
        self.assertIsNone(cod)
        self.assertEqual(len(pends), 1)


# ---------------------------------------------------------------------------
# Normalização de Cargo
# ---------------------------------------------------------------------------

class TestNormalizarCargo(unittest.TestCase):

    def test_cargo_encontrado_exatamente(self):
        cod, descr, pends = normalizar_cargo("VENDEDOR LOJA", CATALOGO_COMPLETO)
        self.assertEqual(cod, 100)
        self.assertEqual(descr, "VENDEDOR LOJA")
        self.assertEqual(pends, [])

    def test_cargo_encontrado_minusculas(self):
        cod, descr, pends = normalizar_cargo("vendedor loja", CATALOGO_COMPLETO)
        self.assertEqual(cod, 100)
        self.assertEqual(descr, "VENDEDOR LOJA")
        self.assertEqual(pends, [])

    def test_cargo_gerente_de_loja_unico(self):
        """GERENTE DE LOJA tem match único no catálogo."""
        cod, descr, pends = normalizar_cargo("GERENTE DE LOJA", CATALOGO_COMPLETO)
        self.assertEqual(cod, 150)
        self.assertEqual(descr, "GERENTE DE LOJA")
        self.assertEqual(pends, [])

    def test_cargo_gerente_quiosque_unico(self):
        """GERENTE QUIOSQUE tem match único no catálogo."""
        cod, descr, pends = normalizar_cargo("GERENTE QUIOSQUE", CATALOGO_COMPLETO)
        self.assertEqual(cod, 151)
        self.assertEqual(descr, "GERENTE QUIOSQUE")
        self.assertEqual(pends, [])

    def test_cargo_ambiguo_mesmo_nome_dois_codigos_gera_pendencia(self):
        """Se o mesmo nome exato mapeia dois códigos distintos, há ambiguidade."""
        contexto_ambiguo = {
            "dicionario_dimensoes": {
                "marcas": {},
                "cargos": {
                    "150": "GERENTE DE LOJA",
                    "155": "GERENTE DE LOJA",  # mesmo nome, dois códigos
                },
                "canais": [],
            }
        }
        cod, descr, pends = normalizar_cargo("GERENTE DE LOJA", contexto_ambiguo)
        self.assertIsNone(cod)
        self.assertIsNone(descr)
        self.assertEqual(len(pends), 1)
        self.assertIn("GERENTE DE LOJA", pends[0])

    def test_cargo_termo_generico_nao_encontrado_gera_pendencia(self):
        """'gerentes' corresponde a dois cargos com códigos distintos em CATALOGO_COMPLETO (150 e 151)."""
        cod, descr, pends = normalizar_cargo("gerentes", CATALOGO_COMPLETO)
        self.assertIsNone(cod)
        self.assertIsNone(descr)
        self.assertEqual(len(pends), 1)

    def test_cargo_ambiguo_mesmo_codigo_cenario_c(self):
        """Cenário C: 'gerentes' corresponde a GERENTE DE LOJA e GERENTE QUIOSQUE ambos com código 150."""
        contexto_cenario_c = {
            "dicionario_dimensoes": {
                "cargos": [
                    {"codCargo": 150, "descriCargo": "GERENTE DE LOJA"},
                    {"codCargo": 150, "descriCargo": "GERENTE QUIOSQUE"},
                ]
            }
        }
        cod, descr, pends = normalizar_cargo("gerentes", contexto_cenario_c)
        self.assertEqual(cod, 150)
        self.assertIsNone(descr)
        self.assertEqual(len(pends), 1)
        self.assertIn("Ambiguidade de cargo", pends[0])

    def test_cargo_none_retorna_null_sem_pendencia(self):
        cod, descr, pends = normalizar_cargo(None, CATALOGO_COMPLETO)
        self.assertIsNone(cod)
        self.assertIsNone(descr)
        self.assertEqual(pends, [])

    def test_cargo_vazio_retorna_null_sem_pendencia(self):
        cod, descr, pends = normalizar_cargo("  ", CATALOGO_COMPLETO)
        self.assertIsNone(cod)
        self.assertIsNone(descr)
        self.assertEqual(pends, [])

    def test_sem_catalogo_retorna_null_sem_pendencia(self):
        cod, descr, pends = normalizar_cargo("VENDEDOR LOJA", {})
        self.assertIsNone(cod)
        self.assertIsNone(descr)
        self.assertEqual(pends, [])

    def test_cargo_assistente_de_vendas(self):
        cod, descr, pends = normalizar_cargo("assistente de vendas", CATALOGO_COMPLETO)
        self.assertEqual(cod, 300)
        self.assertEqual(descr, "ASSISTENTE DE VENDAS")
        self.assertEqual(pends, [])


if __name__ == "__main__":
    unittest.main()
