"""
Repertório de pedidos reais pela interface, para calibração de prompt/normalizadores (IA-1 / BUG-114).

Cobre as categorias pedidas no ticket: múltiplas regras (TestMultiplasRegras), faixas e filtros
(TestFiltrosCombinados), bônus (TestBonus), vigências (TestVigenciasReais), alteração sobre a
base (TestReinterpretacaoPreservaEdicaoManual) e linguagem ambígua (TestLinguagemAmbigua) —
incluindo números escritos por extenso, um gap conhecido hoje (TestNumerosPorExtenso).

Cada caso usa uma saída de LLM simulada (como em test_extrator_campanha.py): o que está sendo
calibrado/validado aqui é a normalização determinística e o anti-alucinação, não o modelo em si
(isso exigiria uma chamada real e não seria reproduzível em CI).
"""

import os
import sys
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from app.core.agente import AgenteInterpretador
from app.core.services.campanha import ExtratorCampanha
from app.core.services.reinterpretador import ServicoReinterpretacao
from app.schemas.proposta import (
    BlocoProposta,
    Condicoes,
    ContextoProposta,
    InterpretarRequestV2,
    Operacao,
    ReinterpretarRequest,
)
from app.tools import BackendClient, criar_registry

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


def codigos(bloco_interno):
    return {p.codigo.value for p in bloco_interno.bloco.pendencias}


class TestFiltrosCombinados(unittest.TestCase):
    """"Filtros" do ticket: matrícula + faixa + canal juntos na mesma regra, como um gestor digitaria."""

    def test_matricula_com_faixa_e_canal(self):
        texto = "A matrícula MATRIC-56 ganha 6% nas vendas acima de R$ 10 mil pelo ecommerce em outubro de 2026"
        r = extrair(texto, {
            "regras": [{
                "trecho_origem": texto,
                "matricula_raw": "MATRIC-56",
                "taxa_raw": "6%",
                "faixa_min_raw": "R$ 10 mil",
                "faixa_min_inclusivo": False,
                "canal": "ECOMMERCE",
            }],
            "vigencia_inicio_raw": "outubro de 2026", "vigencia_fim_raw": "outubro de 2026",
        })
        b = r.blocos[0].bloco
        self.assertEqual(b.condicoes.matricula, "MATRIC-56")
        self.assertEqual(b.condicoes.canal, "ECOMMERCE")
        self.assertEqual(b.condicoes.faixaValor.min, Decimal("10000.00"))
        self.assertEqual(b.taxa, Decimal("0.0600"))
        self.assertEqual(codigos(r.blocos[0]), set())

    def test_filtro_de_cargo_e_loja_sem_faixa(self):
        texto = "Gerentes de loja da loja 75 recebem 4% em novembro de 2026, sem bônus"
        r = extrair(texto, {
            "regras": [{
                "trecho_origem": "Gerentes de loja da loja 75 recebem 4%",
                "cargo_raw": "gerentes de loja", "loja_raw": "75", "taxa_raw": "4%",
            }],
            "vigencia_inicio_raw": "novembro de 2026", "vigencia_fim_raw": "novembro de 2026",
        })
        b = r.blocos[0].bloco
        self.assertEqual(b.condicoes.codCargo, 150)
        self.assertEqual(b.condicoes.codLoja, 75)
        self.assertIsNone(b.condicoes.faixaValor)


class TestMultiplasRegras(unittest.TestCase):
    """"Múltiplas regras" do ticket: um pedido só gera mais de um bloco, cada um com sua condição."""

    def test_duas_regras_no_mesmo_pedido(self):
        texto = "3% para vendedores da loja 75 e 2% para gerentes de loja em dezembro"
        r = extrair(texto, {
            "regras": [
                {
                    "trecho_origem": "3% para vendedores da loja 75", "cargo_raw": "vendedores",
                    "loja_raw": "75", "taxa_raw": "3%",
                },
                {
                    "trecho_origem": "2% para gerentes de loja", "cargo_raw": "gerentes de loja", "taxa_raw": "2%",
                },
            ],
            "vigencia_inicio_raw": "dezembro", "vigencia_fim_raw": "dezembro",
        })
        self.assertEqual(len(r.blocos), 2)
        b1, b2 = (b.bloco for b in r.blocos)
        self.assertEqual(b1.idLocal, "p1")
        self.assertEqual(b1.condicoes.codCargo, 100)
        self.assertEqual(b1.condicoes.codLoja, 75)
        self.assertEqual(b1.taxa, Decimal("0.0300"))
        self.assertEqual(b2.idLocal, "p2")
        self.assertEqual(b2.condicoes.codCargo, 150)
        self.assertIsNone(b2.condicoes.codLoja)
        self.assertEqual(b2.taxa, Decimal("0.0200"))


class TestBonus(unittest.TestCase):
    """"Bônus" do ticket: adicional sobre a venda, em percentual e/ou valor fixo (sem extenso)."""

    def test_bonus_percentual(self):
        texto = "Taxa de 4% mais 1% de bônus por venda na loja 75 em dezembro"
        r = extrair(texto, {
            "regras": [{
                "trecho_origem": texto, "loja_raw": "75", "taxa_raw": "4%", "bonus_percentual_raw": "1%",
            }],
            "vigencia_inicio_raw": "dezembro", "vigencia_fim_raw": "dezembro",
        })
        b = r.blocos[0].bloco
        self.assertEqual(b.taxa, Decimal("0.0400"))
        self.assertEqual(b.bonus.percentual, Decimal("0.0100"))
        self.assertIsNone(b.bonus.valorFixo)

    def test_bonus_valor_fixo(self):
        texto = "2% de comissão mais R$ 30,00 fixo por venda na loja 75 em dezembro"
        r = extrair(texto, {
            "regras": [{
                "trecho_origem": texto, "loja_raw": "75", "taxa_raw": "2%", "bonus_valor_raw": "R$ 30,00",
            }],
            "vigencia_inicio_raw": "dezembro", "vigencia_fim_raw": "dezembro",
        })
        b = r.blocos[0].bloco
        self.assertEqual(b.bonus.valorFixo, Decimal("30.00"))
        self.assertIsNone(b.bonus.percentual)


class TestVigenciasReais(unittest.TestCase):
    def test_vigencia_com_datas_explicitas(self):
        texto = "De 01/03/2026 até 30/06/2026, pagar 7% no ecommerce"
        r = extrair(texto, {
            "regras": [{
                "trecho_origem": "pagar 7% no ecommerce", "taxa_raw": "7%", "canal": "ECOMMERCE",
            }],
            "vigencia_inicio_raw": "01/03/2026", "vigencia_fim_raw": "30/06/2026",
        })
        b = r.blocos[0].bloco
        self.assertEqual((b.dataInicio, b.dataFim), (date(2026, 3, 1), date(2026, 6, 30)))

    def test_vigencia_em_aberto_a_partir_de(self):
        texto = "A partir de janeiro de 2027, 5% para todas as lojas físicas"
        r = extrair(texto, {
            "regras": [{"trecho_origem": "5% para todas as lojas físicas", "taxa_raw": "5%", "canal": "LOJA_FISICA"}],
            "vigencia_inicio_raw": "a partir de janeiro de 2027", "vigencia_fim_raw": None,
        })
        b = r.blocos[0].bloco
        self.assertEqual(b.dataInicio, date(2027, 1, 1))
        self.assertIsNone(b.dataFim)


class TestLinguagemAmbigua(unittest.TestCase):
    def test_cargo_ambiguo_nao_escolhe_sozinho(self):
        texto = "Gerentes ganham 3% em dezembro"
        r = extrair(texto, {
            "regras": [{"trecho_origem": "Gerentes ganham 3%", "taxa_raw": "3%", "cargo_raw": "gerentes"}],
            "vigencia_inicio_raw": "dezembro", "vigencia_fim_raw": "dezembro",
        })
        self.assertIsNone(r.blocos[0].bloco.condicoes.codCargo)
        self.assertIn("AMBIGUIDADE_CARGO", codigos(r.blocos[0]))

    def test_criterio_nao_suportado_vira_pendencia_sem_inventar(self):
        texto = "Pagar 5% apenas para clientes recorrentes"
        r = extrair(texto, {
            "regras": [{
                "trecho_origem": texto, "taxa_raw": "5%",
                "criterios_nao_suportados": ["cliente recorrente"],
            }],
        })
        self.assertIn("CRITERIO_NAO_SUPORTADO", codigos(r.blocos[0]))
        # o campo correspondente não existe no schema: nada foi inventado para representá-lo
        self.assertEqual(r.blocos[0].bloco.condicoes.canal, None)


class TestNumerosPorExtenso(unittest.TestCase):
    """
    Gap apontado pelo Gabriel, agora coberto por `normalizers/extenso.py`: número escrito
    totalmente por extenso ("dez por cento", "cinco mil reais", "mil e quinhentos reais") é
    convertido deterministicamente, sem o LLM precisar (ou poder) resolver a conta sozinho.
    """

    def test_taxa_por_extenso(self):
        texto = "A comissão é de dez por cento no ecommerce em dezembro"
        r = extrair(texto, {
            "regras": [{"trecho_origem": texto, "taxa_raw": "dez por cento", "canal": "ECOMMERCE"}],
            "vigencia_inicio_raw": "dezembro", "vigencia_fim_raw": "dezembro",
        })
        b = r.blocos[0].bloco
        self.assertEqual(b.taxa, Decimal("0.1000"))
        self.assertEqual(codigos(r.blocos[0]), set())

    def test_valor_de_faixa_por_extenso(self):
        texto = "2% nas vendas até cinco mil reais"
        r = extrair(texto, {
            "regras": [{"trecho_origem": texto, "taxa_raw": "2%", "faixa_max_raw": "cinco mil reais"}],
        })
        b = r.blocos[0].bloco
        self.assertEqual(b.condicoes.faixaValor.max, Decimal("5000.00"))

    def test_bonus_composto_por_extenso(self):
        texto = "Bônus de mil e quinhentos reais por venda"
        r = extrair(texto, {
            "regras": [{
                "trecho_origem": texto, "taxa_raw": "5%", "bonus_valor_raw": "mil e quinhentos reais",
            }],
        })
        b = r.blocos[0].bloco
        self.assertEqual(b.bonus.valorFixo, Decimal("1500.00"))


class TestReinterpretacaoPreservaEdicaoManual(unittest.TestCase):
    """"Preservar edições manuais e comparar resultados antes/depois" do ticket."""

    def _backend_sem_lacunas(self):
        def h(req: httpx.Request):
            p = req.url.path
            if p.endswith("/regras-concorrentes"):
                return httpx.Response(200, json={"conflitos": []})
            return httpx.Response(404)

        client = BackendClient(base_url="http://b", timeout=1, transport=httpx.MockTransport(h))
        client.RETRY_BACKOFF_SECONDS = 0
        return client

    def _agente(self, extracao):
        provider = MagicMock()
        provider.complete.return_value = extracao
        registry = criar_registry(self._backend_sem_lacunas())
        return AgenteInterpretador(provider, registry)

    def test_texto_alterado_preserva_campo_nao_citado_e_sinaliza_so_o_que_mudou(self):
        """Usuário tinha editado a taxa manualmente; o texto novo só muda o canal.
        A taxa editada à mão deve ser preservada, e `camposAlterados` só deve apontar o canal."""
        bloco_atual = BlocoProposta(
            idLocal="p1",
            condicoes=Condicoes(canal="ECOMMERCE"),
            taxa=Decimal("0.0450"),  # valor editado manualmente pelo usuário, diferente do que a IA tinha sugerido
            operacao=Operacao(tipo="TAXA_ABSOLUTA", valor=Decimal("0.0450")),
            dataInicio=date(2026, 12, 1),
            dataFim=date(2026, 12, 31),
        )
        agente = self._agente({
            "regras": [{
                "trecho_origem": "4,5% na loja física em dezembro", "taxa_raw": "4,5%", "canal": "LOJA_FISICA",
            }],
            "vigencia_inicio_raw": "dezembro", "vigencia_fim_raw": "dezembro",
        })
        servico = ServicoReinterpretacao(agente)
        req = ReinterpretarRequest(
            contexto=ContextoProposta(origem="NOVA"),
            idLocal="p1",
            textoAlterado="4,5% na loja física em dezembro",
            blocoAtual=bloco_atual,
            dataReferencia=date(2026, 9, 7),
            catalogo=CATALOGO,
        )
        resp = servico.reinterpretar(req)

        nova = resp.propostasSubstituicao[0]
        self.assertEqual(nova.idLocal, "p1")
        self.assertEqual(nova.taxa, Decimal("0.0450"))  # igual ao atual: não houve mudança real de taxa
        self.assertEqual(nova.condicoes.canal, "LOJA_FISICA")
        self.assertEqual(resp.camposAlterados, ["condicoes.canal"])


if __name__ == "__main__":
    unittest.main()
