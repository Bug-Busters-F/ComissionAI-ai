"""
Testes unitários para o normalizador determinístico de datas (Task S1-A04).
"""

from datetime import date
import unittest

from app.core.normalizers.datas import normalizar_datas


class TestNormalizadorDatas(unittest.TestCase):
    def test_normalizar_mes_unico(self):
        dt_inicio, dt_fim, pendencias = normalizar_datas("dezembro", "dezembro", {"ano_referencia": 2026})
        self.assertEqual(dt_inicio, date(2026, 12, 1))
        self.assertEqual(dt_fim, date(2026, 12, 31))
        self.assertEqual(pendencias, [])

    def test_normalizar_mes_sem_fim_especificado(self):
        dt_inicio, dt_fim, pendencias = normalizar_datas("dezembro", None, {"ano_referencia": 2026})
        self.assertEqual(dt_inicio, date(2026, 12, 1))
        self.assertEqual(dt_fim, date(2026, 12, 31))
        self.assertEqual(pendencias, [])

    def test_normalizar_a_partir_de_mes(self):
        dt_inicio, dt_fim, pendencias = normalizar_datas("a partir de outubro", None, {"ano_referencia": 2026})
        self.assertEqual(dt_inicio, date(2026, 10, 1))
        self.assertIsNone(dt_fim)
        self.assertEqual(pendencias, [])

    def test_normalizar_intervalo_meses(self):
        dt_inicio, dt_fim, pendencias = normalizar_datas(
            "de janeiro a marco",
            None,
            {"ano_referencia": 2026},
        )
        self.assertEqual(dt_inicio, date(2026, 1, 1))
        self.assertEqual(dt_fim, date(2026, 3, 31))
        self.assertEqual(pendencias, [])

    def test_normalizar_trimestre(self):
        dt_inicio, dt_fim, pendencias = normalizar_datas(
            "1º trimestre",
            "1º trimestre",
            {"ano_referencia": 2026},
        )
        self.assertEqual(dt_inicio, date(2026, 1, 1))
        self.assertEqual(dt_fim, date(2026, 3, 31))
        self.assertEqual(pendencias, [])

    def test_normalizar_datas_iso(self):
        dt_inicio, dt_fim, pendencias = normalizar_datas(
            "2026-10-01",
            "2026-12-31",
        )
        self.assertEqual(dt_inicio, date(2026, 10, 1))
        self.assertEqual(dt_fim, date(2026, 12, 31))
        self.assertEqual(pendencias, [])

    def test_normalizar_datas_brasileiras(self):
        dt_inicio, dt_fim, pendencias = normalizar_datas(
            "01/10/2026",
            "31/12/2026",
        )
        self.assertEqual(dt_inicio, date(2026, 10, 1))
        self.assertEqual(dt_fim, date(2026, 12, 31))
        self.assertEqual(pendencias, [])

    def test_normalizar_data_fim_anterior_ao_inicio(self):
        dt_inicio, dt_fim, pendencias = normalizar_datas(
            "2026-12-01",
            "2026-10-01",
        )
        self.assertIsNone(dt_inicio)
        self.assertIsNone(dt_fim)
        self.assertEqual(len(pendencias), 1)
        self.assertIn("anterior", pendencias[0])

    def test_normalizar_data_vazia(self):
        dt_inicio, dt_fim, pendencias = normalizar_datas(None, None)
        self.assertIsNone(dt_inicio)
        self.assertIsNone(dt_fim)
        self.assertEqual(len(pendencias), 1)


if __name__ == "__main__":
    unittest.main()
