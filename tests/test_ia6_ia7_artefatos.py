"""
Testes das tarefas IA-6 (BUG-57) e IA-7 (BUG-58):
- Reinterpretação localizada e atualização de artefatos após edição manual
- Geração de explicações rastreáveis e código Python
"""

import os
import sys
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from app.core.agente import AgenteInterpretador
from app.core.agente.hooks import HooksAjusteSobreBase
from app.core.config import settings
from app.core.normalizers.taxa import interpretar_operacao
from app.core.prompts.codigo_regra_prompt import gerar_codigo_regra
from app.core.prompts.explicacao_prompt import gerar_explicacao_bloco
from app.core.services.artefatos import ServicoArtefatos
from app.core.services.reinterpretador import ServicoReinterpretacao
from app.core.simulacao.validador import validar_codigo
from app.schemas.proposta import (
    AtualizarArtefatosRequest,
    BlocoProposta,
    CodigoPendencia,
    Condicoes,
    ContextoProposta,
    FaixaValor,
    Operacao,
    Origem,
    ReinterpretarRequest,
    ReferenciaBase,
)
from app.tools import BackendClient, criar_registry
from app.tools.base import ToolRegistry


class TestIA6ReinterpretacaoEArtefatos(unittest.TestCase):
    """Testes de IA-6: reinterpretação e artefatos após edição manual."""

    def test_reinterpretar_divide_em_dois_blocos_e_preserva_ids(self):
        # Simula agente retornando 2 regras
        saida_llm = {
            "regras": [
                {"trecho_origem": "2% loja 75", "taxa_raw": "2%", "loja_raw": "75"},
                {"trecho_origem": "4% ecommerce", "taxa_raw": "4%", "canal": "ECOMMERCE"},
            ],
            "vigencia_inicio_raw": "2026-12-01",
            "vigencia_fim_raw": "2026-12-31",
        }
        provider = MagicMock()
        provider.complete.return_value = saida_llm
        agente = AgenteInterpretador(provider, ToolRegistry())
        servico = ServicoReinterpretacao(agente)

        bloco_atual = BlocoProposta(
            idLocal="p1",
            taxa=Decimal("0.0300"),
            condicoes=Condicoes(codCargo=100),
            dataInicio=date(2026, 12, 1),
            dataFim=date(2026, 12, 31),
        )
        demais = [
            BlocoProposta(
                idLocal="p2",
                taxa=Decimal("0.0500"),
                condicoes=Condicoes(codCargo=200),
                dataInicio=date(2026, 12, 1),
                dataFim=date(2026, 12, 31),
            )
        ]

        req = ReinterpretarRequest(
            idLocal="p1",
            textoAlterado="2% loja 75 e 4% ecommerce",
            blocoAtual=bloco_atual,
            demaisBlocos=demais,
        )

        resp = servico.reinterpretar(req)
        self.assertEqual(len(resp.propostasSubstituicao), 2)
        # Primeiro mantém p1, segundo p1_2
        self.assertEqual(resp.propostasSubstituicao[0].idLocal, "p1")
        self.assertEqual(resp.propostasSubstituicao[1].idLocal, "p1_2")
        # Campos alterados detectados
        self.assertIn("taxa", resp.camposAlterados)
        # Demais blocos não foram alterados
        self.assertEqual(demais[0].idLocal, "p2")
        self.assertEqual(demais[0].taxa, Decimal("0.0500"))

    def test_reinterpretar_detecta_conflito_com_demais_blocos(self):
        # Simula agente retornando regra sobreposta a um dos demaisBlocos
        saida_llm = {
            "regras": [
                {"trecho_origem": "5% para cargo 200", "taxa_raw": "5%", "cargo_raw": "GERENTE"},
            ],
            "vigencia_inicio_raw": "2026-12-01",
            "vigencia_fim_raw": "2026-12-31",
        }
        provider = MagicMock()
        provider.complete.return_value = saida_llm
        agente = AgenteInterpretador(provider, ToolRegistry(), hooks=HooksAjusteSobreBase())
        servico = ServicoReinterpretacao(agente)

        bloco_atual = BlocoProposta(
            idLocal="p1",
            taxa=Decimal("0.0300"),
            condicoes=Condicoes(codCargo=100),
            dataInicio=date(2026, 12, 1),
            dataFim=date(2026, 12, 31),
        )
        demais = [
            BlocoProposta(
                idLocal="p2",
                taxa=Decimal("0.0500"),
                condicoes=Condicoes(codCargo=200),
                dataInicio=date(2026, 12, 1),
                dataFim=date(2026, 12, 31),
            )
        ]

        req = ReinterpretarRequest(
            idLocal="p1",
            textoAlterado="5% para cargo 200",
            blocoAtual=bloco_atual,
            demaisBlocos=demais,
            catalogo={"cargos": {"200": "GERENTE"}},
        )

        resp = servico.reinterpretar(req)
        p_nova = resp.propostasSubstituicao[0]
        # Conflito de público e vigência deve gerar CONFLITO_REGRA
        self.assertTrue(any(p.codigo == CodigoPendencia.CONFLITO_REGRA for p in p_nova.pendencias))

    def test_atualizar_artefatos_preserva_taxa_manual(self):
        bloco = BlocoProposta(
            idLocal="p1",
            taxa=Decimal("0.0600"),
            condicoes=Condicoes(codCargo=100, descriCargo="VENDEDOR"),
            dataInicio=date(2026, 12, 1),
            dataFim=date(2026, 12, 31),
        )
        servico = ServicoArtefatos()
        req = AtualizarArtefatosRequest(
            bloco=bloco,
            camposEditados=["taxa"],
            origemCampos={"taxa": "MANUAL"},
        )
        resp = servico.atualizar(req)
        b_res = resp.bloco
        self.assertEqual(b_res.taxa, Decimal("0.0600"))
        self.assertIn("MANUAL", b_res.explicacao)
        self.assertIsNotNone(b_res.codigoPython)

    def _servico(self, saida_llm):
        provider = MagicMock()
        provider.complete.return_value = saida_llm
        return ServicoReinterpretacao(AgenteInterpretador(provider, ToolRegistry(), hooks=HooksAjusteSobreBase()))

    def _bloco(self, id_local="p1", **kw):
        base = dict(idLocal=id_local, taxa=Decimal("0.0300"), dataInicio=date(2026, 12, 1), dataFim=date(2026, 12, 31))
        base.update(kw)
        return BlocoProposta(**base)

    def test_texto_so_com_taxa_herda_publico_do_bloco_atual(self):
        servico = self._servico({"regras": [{"trecho_origem": "4%", "taxa_raw": "4%"}],
                                 "vigencia_inicio_raw": "2026-12-01", "vigencia_fim_raw": "2026-12-31"})
        atual = self._bloco(condicoes=Condicoes(codCargo=100, descriCargo="VENDEDOR", codLoja=75,
                                                faixaValor=FaixaValor(min=Decimal("100"))))
        resp = servico.reinterpretar(ReinterpretarRequest(idLocal="p1", textoAlterado="4%", blocoAtual=atual))
        nova = resp.propostasSubstituicao[0]
        self.assertEqual(nova.taxa, Decimal("0.0400"))
        self.assertEqual((nova.condicoes.codCargo, nova.condicoes.codLoja), (100, 75))
        self.assertEqual(nova.condicoes.faixaValor, atual.condicoes.faixaValor)
        self.assertEqual(resp.camposAlterados, ["operacao", "taxa"])
        self.assertIn("VENDEDOR", nova.explicacao)

    def test_texto_so_com_publico_herda_taxa_do_bloco_atual(self):
        servico = self._servico({"regras": [{"trecho_origem": "loja 80", "loja_raw": "80"}],
                                 "vigencia_inicio_raw": "2026-12-01", "vigencia_fim_raw": "2026-12-31"})
        atual = self._bloco(condicoes=Condicoes(codLoja=75),
                            operacao=Operacao(tipo="TAXA_ABSOLUTA", valor=Decimal("0.0300")))
        resp = servico.reinterpretar(ReinterpretarRequest(idLocal="p1", textoAlterado="loja 80", blocoAtual=atual))
        nova = resp.propostasSubstituicao[0]
        self.assertEqual((nova.taxa, nova.condicoes.codLoja), (Decimal("0.0300"), 80))
        self.assertFalse(any(p.campo == "taxa" for p in nova.pendencias))
        self.assertEqual(resp.camposAlterados, ["condicoes.codLoja"])

    def test_ajuste_herdado_e_recalculado_com_a_base_do_novo_publico(self):
        # bloco atual: PRETO/VENDEDOR +1 p.p. sobre base 2,5% = 3,5%; o texto novo troca só a marca
        bases = {"10": "0.0250", "20": "0.0300"}

        def spring(req: httpx.Request):
            if req.url.path.endswith("/marcas"):
                return httpx.Response(200, json={"encontrado": True, "itens": [{"codigo": 20, "descricao": "BRANCO"}]})
            if req.url.path.endswith("/cargos"):
                return httpx.Response(200, json={"encontrado": True, "itens": [{"codigo": 100, "descricao": "VENDEDOR LOJA"}]})
            if req.url.path.endswith("/bases"):
                taxa = bases[req.url.params["codMarca"]]
                return httpx.Response(200, json={"encontrado": True, "taxa": taxa, "competenciaUsada": "2026-12"})
            return httpx.Response(200, json={"conflitos": []})

        registry = criar_registry(client=BackendClient(base_url="http://spring", timeout=1,
                                                       transport=httpx.MockTransport(spring)))
        provider = MagicMock()
        provider.complete.return_value = {
            "regras": [{"trecho_origem": "marca branco", "marca_raw": "branco"}],
            "vigencia_inicio_raw": "2026-12-01", "vigencia_fim_raw": "2026-12-31",
        }
        servico = ServicoReinterpretacao(AgenteInterpretador(provider, registry, hooks=HooksAjusteSobreBase()))
        atual = self._bloco(
            taxa=Decimal("0.0350"),
            operacao=Operacao(tipo="ADICIONAR_PP", valor=Decimal("0.0100")),
            condicoes=Condicoes(codMarca=10, descrMarca="PRETO", codCargo=100, descriCargo="VENDEDOR LOJA"),
            referencias=[ReferenciaBase(fonte="BASE_COMISS", taxaBase=Decimal("0.0250"))],
        )
        resp = servico.reinterpretar(ReinterpretarRequest(idLocal="p1", textoAlterado="marca branco", blocoAtual=atual))
        nova = resp.propostasSubstituicao[0]
        self.assertEqual((nova.condicoes.codMarca, nova.condicoes.codCargo), (20, None))
        # sem cargo não há base única: pede restrição em vez de herdar a taxa calculada para PRETO
        self.assertIsNone(nova.taxa)
        self.assertEqual((nova.operacao.tipo, nova.operacao.valor), ("ADICIONAR_PP", Decimal("0.0100")))
        self.assertTrue(any(p.codigo == CodigoPendencia.AMBIGUIDADE_PUBLICO for p in nova.pendencias))

        provider.complete.return_value = {
            "regras": [{"trecho_origem": "marca branco", "marca_raw": "branco", "cargo_raw": "vendedor loja"}],
            "vigencia_inicio_raw": "2026-12-01", "vigencia_fim_raw": "2026-12-31",
        }
        nova = servico.reinterpretar(ReinterpretarRequest(
            idLocal="p1", textoAlterado="marca branco cargo vendedor loja", blocoAtual=atual,
        )).propostasSubstituicao[0]
        self.assertEqual(nova.taxa, Decimal("0.0400"))  # base BRANCO 3% + 1 p.p.
        self.assertEqual([r.taxaBase for r in nova.referencias if r.fonte == "BASE_COMISS"], [Decimal("0.0300")])
        self.assertFalse(any(p.campo == "taxa" for p in nova.pendencias))

    def test_texto_canonico_da_operacao_volta_ao_mesmo_ajuste(self):
        from app.core.agente.hooks import _texto_da_operacao

        for tipo in ("ADICIONAR_PP", "REDUZIR_PP", "AUMENTAR_PERCENTUAL", "REDUZIR_PERCENTUAL"):
            for valor in (Decimal("0.0100"), Decimal("0.0050"), Decimal("0.1250")):
                with self.subTest(tipo=tipo, valor=valor):
                    r = interpretar_operacao(_texto_da_operacao(tipo, valor))
                    self.assertEqual((r.tipo, r.valor), (tipo, valor))

    def test_especificidades_diferentes_nao_sao_conflito(self):
        # loja 75 (8) é mais específica que uma regra sem filtro (0): o motor escolhe pela precedência
        servico = self._servico({"regras": [{"trecho_origem": "5% loja 75", "taxa_raw": "5%", "loja_raw": "75"}],
                                 "vigencia_inicio_raw": "2026-12-01", "vigencia_fim_raw": "2026-12-31"})
        resp = servico.reinterpretar(ReinterpretarRequest(
            idLocal="p1", textoAlterado="5% loja 75", blocoAtual=self._bloco(), demaisBlocos=[self._bloco("p2")]))
        nova = resp.propostasSubstituicao[0]
        self.assertFalse(any(p.codigo == CodigoPendencia.CONFLITO_REGRA for p in nova.pendencias))

    def test_faixas_disjuntas_nao_sao_conflito_e_divisao_e_checada(self):
        servico = self._servico({
            "regras": [
                {"trecho_origem": "2% até 100", "taxa_raw": "2%", "loja_raw": "75", "faixa_max_raw": "100"},
                {"trecho_origem": "4% a partir de 100", "taxa_raw": "4%", "loja_raw": "75", "faixa_min_raw": "100"},
                {"trecho_origem": "5% a partir de 50", "taxa_raw": "5%", "loja_raw": "75", "faixa_min_raw": "50"},
            ],
            "vigencia_inicio_raw": "2026-12-01", "vigencia_fim_raw": "2026-12-31",
        })
        resp = servico.reinterpretar(
            ReinterpretarRequest(idLocal="p1", textoAlterado="faixas", blocoAtual=self._bloco()))
        conflitos = [
            [p for p in b.pendencias if p.codigo == CodigoPendencia.CONFLITO_REGRA]
            for b in resp.propostasSubstituicao
        ]
        # [0,100) x [100,inf): disjuntas; as duas se sobrepõem a [50,inf) com a mesma especificidade
        self.assertEqual([len(c) for c in conflitos], [1, 1, 0])
        self.assertIn("p1_3", conflitos[0][0].mensagem)

    def test_atualizar_artefatos_campo_editado_sem_origem_e_manual(self):
        bloco = self._bloco(
            taxa=Decimal("0.0450"),
            operacao=Operacao(tipo="ADICIONAR_PP", valor=Decimal("0.0100")),
            referencias=[ReferenciaBase(fonte="BASE_COMISS", taxaBase=Decimal("0.0250"))],
        )
        resp = ServicoArtefatos().atualizar(AtualizarArtefatosRequest(bloco=bloco, camposEditados=["taxa"]))
        b = resp.bloco
        self.assertIn("4,50% definida manualmente", b.explicacao)
        self.assertNotIn("Base de comissão consultada", b.explicacao)
        self.assertEqual((b.operacao.tipo, b.operacao.valor), ("TAXA_ABSOLUTA", Decimal("0.0450")))
        self.assertFalse(any(r.fonte == "BASE_COMISS" for r in b.referencias))
        self.assertIn("Decimal('0.0450')", b.codigoPython)

    def test_atualizar_artefatos_nao_reinterpreta_campos(self):
        bloco = self._bloco(condicoes=Condicoes(codCargo=100), origem=Origem(trecho="3% para gerentes"))
        resp = ServicoArtefatos().atualizar(
            AtualizarArtefatosRequest(bloco=bloco, camposEditados=["condicoes.codCargo"]))
        b = resp.bloco
        self.assertEqual((b.taxa, b.condicoes.codCargo), (Decimal("0.0300"), 100))
        self.assertIn("(cód. 100) (edição manual)", b.explicacao)


class TestIA7ExplicacoesECodigo(unittest.TestCase):
    """Testes de IA-7: geração de explicações rastreáveis e código Python estático."""

    def test_explicacao_taxa_absoluta_cita_trecho(self):
        bloco = BlocoProposta(
            idLocal="p1",
            taxa=Decimal("0.0300"),
            origem=Origem(trecho="3% para vendedores"),
            condicoes=Condicoes(codCargo=100, descriCargo="VENDEDOR"),
        )
        exp = gerar_explicacao_bloco(bloco)
        self.assertIn("3% para vendedores", exp)
        self.assertIn("VENDEDOR", exp)

    def test_explicacao_taxa_sobre_base_cita_base(self):
        bloco = BlocoProposta(
            idLocal="p1",
            taxa=Decimal("0.0350"),
            operacao=Operacao(tipo="ADICIONAR_PP", valor=Decimal("0.0100")),
            referencias=[
                ReferenciaBase(
                    fonte="BASE_COMISS",
                    taxaBase=Decimal("0.0250"),
                    chave={"codMarca": 10, "codCargo": 100, "competencia": "2026-12"},
                ),
            ],
            condicoes=Condicoes(codCargo=100, descriCargo="VENDEDOR"),
        )
        exp = gerar_explicacao_bloco(bloco)
        self.assertIn("2,50%", exp)
        self.assertIn("+1,00 p.p.", exp)
        self.assertIn("3,50%", exp)
        self.assertIn("competência 2026-12", exp)

    def test_codigo_python_valido_na_analise_estatica(self):
        bloco = BlocoProposta(
            idLocal="p1",
            taxa=Decimal("0.0300"),
            condicoes=Condicoes(
                codCargo=100,
                codMarca=10,
                codLoja=75,
                faixaValor=FaixaValor(min=Decimal("100"), max=Decimal("500")),
            ),
            dataInicio=date(2026, 10, 1),
            dataFim=date(2026, 10, 31),
        )
        codigo = gerar_codigo_regra(bloco)
        # Validação estrita AST de segurança do sandbox
        val = validar_codigo(
            codigo,
            max_linhas=settings.sim_max_code_lines,
            max_bytes=settings.sim_max_code_bytes,
        )
        self.assertTrue(val.ok, val.violacoes)
        self.assertIn("def simular(vendas, regras, cenario):", codigo)

    def test_codigo_escapa_valores_do_bloco(self):
        malicioso = "p1'}]; __import__('os').system('echo X') #"
        bloco = BlocoProposta(idLocal=malicioso, taxa=Decimal("0.0300"), condicoes=Condicoes(matricula="a' or '1"))
        codigo = gerar_codigo_regra(bloco)
        self.assertIsNotNone(codigo)
        self.assertIn(repr(malicioso), codigo)
        self.assertTrue(validar_codigo(codigo, settings.sim_max_code_lines, settings.sim_max_code_bytes).ok)

    def test_codigo_invalido_nunca_e_devolvido(self):
        bloco = BlocoProposta(idLocal="p1", taxa=Decimal("0.0300"))
        with patch.object(settings, "sim_max_code_lines", 10):
            self.assertIsNone(gerar_codigo_regra(bloco))

    def test_codigo_nao_contem_imports_proibidos(self):
        codigo = gerar_codigo_regra(BlocoProposta(idLocal="p1", taxa=Decimal("0.0300")))
        for proibido in ("import os", "import sys", "subprocess", "socket", "httpx", "requests", "open("):
            self.assertNotIn(proibido, codigo)


if __name__ == "__main__":
    unittest.main()
