"""Testes da geração das bases limpas de RH e Vendas (IA-9 / BUG-122)."""

import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts", "bases_limpas")))

from limpeza import (  # noqa: E402
    LAYOUT_RH,
    LAYOUT_VENDAS,
    Planilha,
    Registro,
    carregar_taxas,
    competencia_do_nome,
    conferir_totais,
    converter_planilha,
    hash_conteudo,
    limpar_rh,
    limpar_vendas,
    verificar_cadastros,
)

CAB_RH = ["Data_Ref", "Cod_Marca", "Descri_Marca", "Cod_Loja", "Descr_Loja", "Matricula ", "Data_Admiss ",
          "Data_Demiss", "Cod_Cargo ", "Descri_Cargo "]
CAB_VENDAS = ["Date_Ref", "Cod_Marca", "Descr_Marca", "Cod_Loja", "Descr_Loja", "Matricula", "Vlr _Venda"]
CAB_TAXAS = ["Cod_Marca", "Descr_Marca", "Cod_Cargo", "Descri_Cargo", "%_Comiss"]


def rh(mat, loja=1, marca=10, cargo=100, descr="VENDEDOR LOJA", adm=datetime(2020, 1, 1), dem=None,
       ref=datetime(2025, 11, 1)):
    return (ref, marca, "PRETO" if marca == 10 else "BRANCO", loja, f"LOJA-{loja}", mat, adm, dem, cargo, descr)


def venda(mat, valor, loja=1, marca=10, ref=datetime(2025, 11, 1)):
    return (ref, marca, "PRETO" if marca == 10 else "BRANCO", loja, f"LOJA-{loja}", mat, valor)


def planilha(nome, cab, linhas):
    return Planilha(nome, list(cab), [(i + 2, tuple(l)) for i, l in enumerate(linhas)])


def taxas_padrao(registro):
    return carregar_taxas(planilha("BASE_COMMISS_FINAL.xlsx", CAB_TAXAS, [
        (10, "PRETO", 100, "VENDEDOR LOJA", 0.025),
        (10, "PRETO", 150, "GERENTE DE LOJA", 0.01),
        (20, "BRANCO", 100, "VENDEDOR LOJA", 0.02),
    ]), registro)


def regras(registro, regra):
    return [c for c in registro.correcoes if c.regra == regra]


class TestCompetencia(unittest.TestCase):
    def test_nomes_reais(self):
        self.assertEqual(competencia_do_nome("BASE_VENDAS_JUL25.xlsx"), "2025-07")
        self.assertEqual(competencia_do_nome("BASE RH_DEZ25.xlsx"), "2025-12")

    def test_nome_sem_competencia(self):
        with self.assertRaises(ValueError):
            competencia_do_nome("BASE.xlsx")


class TestConversao(unittest.TestCase):
    def test_cabecalho_padronizado_e_coluna_extra_removida(self):
        reg = Registro()
        cab = CAB_RH + ["VENDAS R$"]
        base = converter_planilha(planilha("RH_SET25.xlsx", cab, [rh("M1") + (2522.5,)]), "RH", LAYOUT_RH, reg,
                                  "2025-11")
        self.assertEqual(len(base.registros), 1)
        self.assertNotIn("vendas", base.registros[0])
        self.assertEqual(len(regras(reg, "COLUNA_FORA_DO_LAYOUT")), 1)
        self.assertEqual({c.campo for c in regras(reg, "CABECALHO_PADRONIZADO")},
                         {"Matricula", "Data_Admiss", "Cod_Cargo", "Descri_Cargo"})

    def test_coluna_obrigatoria_ausente(self):
        with self.assertRaises(ValueError):
            converter_planilha(planilha("V.xlsx", CAB_VENDAS[:-1], []), "VENDAS", LAYOUT_VENDAS, Registro())

    def test_valor_decimal_em_duas_casas(self):
        reg = Registro()
        base = converter_planilha(planilha("V.xlsx", CAB_VENDAS, [venda("M1", 11.4), venda("M2", 10.005)]),
                                  "VENDAS", LAYOUT_VENDAS, reg, "2025-11")
        self.assertEqual([r["valor"] for r in base.registros], [Decimal("11.40"), Decimal("10.01")])
        self.assertEqual(len(regras(reg, "VALOR_ARREDONDADO")), 1)

    def test_erros_estruturais_saem_da_base(self):
        reg = Registro()
        linhas = [venda("M1", 0), venda("M2", 100, ref=datetime(2025, 10, 1)), venda(None, 100), venda("M3", 50)]
        base = converter_planilha(planilha("V.xlsx", CAB_VENDAS, linhas), "VENDAS", LAYOUT_VENDAS, reg, "2025-11")
        self.assertEqual([r["matricula"] for r in base.registros], ["M3"])
        self.assertEqual(len(regras(reg, "ERRO_ESTRUTURAL")), 3)
        conferir_totais(base, reg)

    def test_demissao_antes_da_admissao(self):
        reg = Registro()
        linha = rh("M1", adm=datetime(2025, 5, 1), dem=datetime(2025, 4, 1))
        base = converter_planilha(planilha("R.xlsx", CAB_RH, [linha]), "RH", LAYOUT_RH, reg, "2025-11")
        self.assertEqual(base.registros, [])


class TestLimpeza(unittest.TestCase):
    def preparar(self, linhas_rh, linhas_vendas, outras_competencias=None):
        self.reg = Registro()
        self.taxas = taxas_padrao(self.reg)
        self.rh = converter_planilha(planilha("RH_NOV25.xlsx", CAB_RH, linhas_rh), "RH", LAYOUT_RH, self.reg,
                                     "2025-11")
        self.vendas = converter_planilha(planilha("VENDAS_NOV25.xlsx", CAB_VENDAS, linhas_vendas), "VENDAS",
                                         LAYOUT_VENDAS, self.reg, "2025-11")
        limpar_rh(self.rh, self.taxas, self.reg)
        mats = {"2025-11": {r["matricula"] for r in self.rh.registros}, **(outras_competencias or {})}
        limpar_vendas(self.vendas, self.rh, self.taxas, mats, self.reg)

    def test_rh_duplicado_identico_conta_uma_vez(self):
        self.preparar([rh("M1"), rh("M1")], [])
        self.assertEqual(len(self.rh.registros), 1)
        self.assertEqual(regras(self.reg, "RH_DUPLICADO")[0].linha, 3)
        conferir_totais(self.rh, self.reg)

    def test_rh_repetido_com_dados_diferentes_vira_pendencia(self):
        self.preparar([rh("M1"), rh("M1", loja=2)], [])
        self.assertEqual(len(self.rh.registros), 2)
        self.assertEqual(len(regras(self.reg, "RH_MATRICULA_REPETIDA_DIVERGENTE")), 1)

    def test_venda_sem_rh_e_desconsiderada_com_evidencia(self):
        self.preparar([rh("M1")], [venda("M1", 100), venda("M9", 200)], {"2025-10": {"M9"}})
        self.assertEqual([v["matricula"] for v in self.vendas.registros], ["M1"])
        erro = regras(self.reg, "VENDA_SEM_RH")[0]
        self.assertEqual((erro.tipo, erro.acao), ("ERRO", "REMOVIDA"))
        self.assertIn("2025-10", erro.justificativa)
        conferir_totais(self.vendas, self.reg)

    def test_venda_duplicada_conta_uma_vez(self):
        self.preparar([rh("M1")], [venda("M1", 100), venda("M1", 100.0), venda("M1", 100, loja=2)])
        self.assertEqual(len(self.vendas.registros), 2)
        dup = regras(self.reg, "VENDA_DUPLICADA")
        self.assertEqual([(d.linha, d.acao) for d in dup], [(3, "REMOVIDA")])
        self.assertIn("linha 2", dup[0].justificativa)

    def test_divergencias_ficam_como_pendencia_sem_alterar_a_venda(self):
        self.preparar([rh("M1", dem=datetime(2025, 11, 20))],
                      [venda("M1", 100, loja=5, marca=20, ref=datetime(2025, 11, 24))])
        self.assertEqual(len(self.vendas.registros), 1)
        v = self.vendas.registros[0]
        self.assertEqual((v["cod_loja"], v["cod_marca"], v["valor"]), (5, 20, Decimal("100.00")))
        for regra in ("LOJA_DIVERGENTE_RH", "MARCA_DIVERGENTE_RH", "VENDA_APOS_DEMISSAO"):
            self.assertEqual(len(regras(self.reg, regra)), 1, regra)

    def test_venda_no_dia_1_com_admissao_no_mesmo_mes_nao_e_pendencia(self):
        self.preparar([rh("M1", adm=datetime(2025, 11, 17)), rh("M2", adm=datetime(2025, 12, 3))],
                      [venda("M1", 100), venda("M2", 100)])
        antes = regras(self.reg, "VENDA_ANTES_ADMISSAO")
        self.assertEqual([a.matricula for a in antes], ["M2"])

    def test_sem_taxa_contratual(self):
        self.preparar([rh("M1", cargo=300, descr="ASSISTENTE DE VENDAS")], [venda("M1", 100)])
        sem_taxa = regras(self.reg, "SEM_TAXA_CONTRATUAL")
        self.assertEqual(len(sem_taxa), 2)  # uma no RH, uma na venda
        self.assertEqual(len(self.vendas.registros), 1)

    def test_gerente_de_loja_usa_descricao_para_achar_taxa(self):
        self.preparar([rh("M1", cargo=150, descr="gerente  de loja")], [venda("M1", 100)])
        self.assertEqual(regras(self.reg, "SEM_TAXA_CONTRATUAL"), [])

    def test_cadastro_inconsistente_entre_bases(self):
        self.preparar([rh("M1"), rh("M2", loja=1, marca=20)], [])
        verificar_cadastros([self.rh], self.reg)
        campos = {c.campo for c in regras(self.reg, "CADASTRO_INCONSISTENTE")}
        self.assertIn("Cod_Marca da loja", campos)

    def test_hash_deterministico(self):
        self.preparar([rh("M1")], [venda("M1", 100), venda("M1", 50)])
        h1 = hash_conteudo(self.vendas)
        self.preparar([rh("M1")], [venda("M1", 100), venda("M1", 50)])
        self.assertEqual(h1, hash_conteudo(self.vendas))
        self.preparar([rh("M1")], [venda("M1", 100), venda("M1", 51)])
        self.assertNotEqual(h1, hash_conteudo(self.vendas))


class TestGeracaoArquivos(unittest.TestCase):
    """Ponta a ponta com planilhas temporárias (requer openpyxl)."""

    def setUp(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl não instalado")
        self.openpyxl = openpyxl
        self.tmp = Path(tempfile.mkdtemp(prefix="bases_"))
        self.origem = self.tmp / "origem"
        self.salvar(self.origem / "BASE_COMMISS_FINAL.xlsx", CAB_TAXAS, [(10, "PRETO", 100, "VENDEDOR LOJA", 0.025)])
        self.salvar(self.origem / "BASE RH" / "BASE RH_NOV25.xlsx", CAB_RH, [rh("M1"), rh("M1")])
        self.salvar(self.origem / "BASE_VENDAS" / "BASE_VENDAS_NOV25.xlsx", CAB_VENDAS,
                    [venda("M1", 10), venda("M1", 10), venda("M9", 5)])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def salvar(self, caminho, cab, linhas):
        caminho.parent.mkdir(parents=True, exist_ok=True)
        wb = self.openpyxl.Workbook()
        wb.active.append(cab)
        for l in linhas:
            wb.active.append(list(l))
        wb.save(caminho)

    def test_gera_arquivos_importaveis_sem_tocar_originais(self):
        import gerar

        antes = {p: p.read_bytes() for p in self.origem.rglob("*.xlsx")}
        destino = self.tmp / "limpas"
        resumo = gerar.executar(self.origem, destino)

        self.assertEqual({p: p.read_bytes() for p in self.origem.rglob("*.xlsx")}, antes)
        ws = self.openpyxl.load_workbook(destino / "vendas" / "VENDAS_2025-11.xlsx").active
        linhas = list(ws.iter_rows(values_only=True))
        self.assertEqual(linhas[0], tuple(c.cabecalho for c in LAYOUT_VENDAS))
        self.assertEqual(len(linhas), 2)  # cabeçalho + 1 venda (duplicada e sem RH removidas)
        self.assertEqual(linhas[1][0].date(), date(2025, 11, 1))
        self.assertTrue((destino / "registro_correcoes.csv").is_file())
        vendas = next(a for a in resumo["arquivos"] if a["tipo"] == "VENDAS")
        self.assertEqual(vendas["linhasRemovidas"], {"VENDA_DUPLICADA": 1, "VENDA_SEM_RH": 1})

    def test_destino_dentro_da_origem_e_recusado(self):
        import gerar

        with self.assertRaises(SystemExit):
            gerar.executar(self.origem, self.origem / "limpas")


if __name__ == "__main__":
    unittest.main()
