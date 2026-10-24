"""Consultas do fluxo padrão: uma extração, sem decisões adicionais pelo LLM."""

import json
import os
import sys
import unittest
from decimal import Decimal
from unittest.mock import patch

import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from app.core.agente import AgenteInterpretador, Limites
from app.core.exceptions import LLMRateLimitError
from app.schemas.proposta import ContextoProposta
from app.tools import criar_registry
from test_agente import backend, cod, llm, req


@patch('app.core.config.settings.agent_use_llm_decisions', False)
class TestConsultasDeterministicas(unittest.TestCase):
    def test_tres_regras_uma_chamada_llm_com_cache_e_evidencias_por_bloco(self):
        trechos = [
            '3,5% no canal LOJA_FISICA abaixo de R$ 1.000,00',
            '5% no canal LOJA_FISICA a partir de R$ 1.000,00',
            '4% no canal BALCAO sem restrição de valor',
        ]
        extracao = {'regras': [
            {'trecho_origem': trechos[0], 'taxa_raw': '3,5%', 'canal': 'LOJA_FISICA',
             'faixa_max_raw': 'R$ 1.000,00', 'faixa_max_inclusivo': False},
            {'trecho_origem': trechos[1], 'taxa_raw': '5%', 'canal': 'LOJA_FISICA',
             'faixa_min_raw': 'R$ 1.000,00', 'faixa_min_inclusivo': True},
            {'trecho_origem': trechos[2], 'taxa_raw': '4%', 'canal': 'BALCAO'},
        ], 'vigencia_inicio_raw': '01/10/2026', 'vigencia_fim_raw': '31/10/2026'}
        client, chamadas = backend()
        provider = llm([], extracao=extracao)
        r = AgenteInterpretador(provider, criar_registry(client)).executar(req(texto='; '.join(trechos)))
        self.assertEqual(provider.complete.call_count, 1)
        self.assertEqual(len(r.propostas), 3)
        self.assertEqual(chamadas.count('/api/v1/consultas-ia/regras-concorrentes'), 2)
        self.assertEqual(len(r.trilhaFerramentas), 3)
        self.assertEqual([e.blocosAfetados for e in r.trilhaFerramentas], [['p1'], ['p2'], ['p3']])
        self.assertIn('reaproveitado', r.propostas[1].evidencias[0].resumo)
        self.assertEqual([p.taxa for p in r.propostas], [Decimal('0.0350'), Decimal('0.0500'), Decimal('0.0400')])
        self.assertEqual(r.propostas[0].condicoes.faixaValor.max, Decimal('1000.00'))
        self.assertFalse(r.propostas[0].condicoes.faixaValor.maxInclusivo)
        self.assertTrue(r.propostas[1].condicoes.faixaValor.minInclusivo)
        for p in r.propostas:
            self.assertNotIn('TOOL_FALHA', cod(p))
            self.assertNotIn('LIMITE_AGENTE_ATINGIDO', cod(p))

    def test_cache_atende_muitos_blocos_mesmo_no_limite_de_novas_consultas(self):
        trecho = '3% para a loja 75'
        provider = llm([], extracao={'regras': [
            {'trecho_origem': trecho, 'taxa_raw': '3%', 'loja_raw': '75'} for _ in range(15)
        ], 'vigencia_inicio_raw': 'dezembro'})
        client, chamadas = backend()
        r = AgenteInterpretador(provider, criar_registry(client), limites=Limites(max_steps=2, max_tool_calls=1)).executar(
            req(texto=trecho + ' em dezembro'))
        self.assertEqual(provider.complete.call_count, 1)
        self.assertEqual(len(chamadas), 1)
        self.assertEqual(len(r.trilhaFerramentas), 15)
        self.assertTrue(all('LIMITE_AGENTE_ATINGIDO' not in cod(p) for p in r.propostas))

    def test_nao_consome_cache_de_outro_publico_quando_orcamento_acaba(self):
        ext = {'regras': [
            {'trecho_origem': '3% para loja 75', 'taxa_raw': '3%', 'loja_raw': '75'},
            {'trecho_origem': '4% para loja 76', 'taxa_raw': '4%', 'loja_raw': '76'},
        ], 'vigencia_inicio_raw': 'dezembro'}
        client, chamadas = backend()
        r = AgenteInterpretador(llm([], extracao=ext), criar_registry(client), limites=Limites(max_tool_calls=1)).executar(
            req(texto='3% para loja 75 e 4% para loja 76 em dezembro'))
        self.assertEqual(len(chamadas), 1)
        self.assertNotIn('LIMITE_AGENTE_ATINGIDO', cod(r.propostas[0]))
        self.assertIn('LIMITE_AGENTE_ATINGIDO', cod(r.propostas[1]))
        self.assertEqual(r.propostas[1].condicoes.codLoja, 76)
        self.assertEqual(r.propostas[1].taxa, Decimal('0.0400'))

    def test_resolve_cadastro_antes_da_concorrencia_e_preserva_ambiguidades(self):
        client, chamadas = backend()
        provider = llm([])
        r = AgenteInterpretador(provider, criar_registry(client)).executar(req())
        self.assertEqual(provider.complete.call_count, 1)
        self.assertEqual([e.ferramenta for e in r.trilhaFerramentas], [
            'resolver_publico', 'validar_matricula', 'consultar_regras_concorrentes', 'consultar_regras_concorrentes'])
        self.assertIn('AMBIGUIDADE_CARGO', cod(r.propostas[0]))
        self.assertIsNone(r.propostas[0].condicoes.codCargo)
        self.assertEqual(r.propostas[0].condicoes.codLoja, 75)
        self.assertTrue(any(p.endswith('/matriculas/MATRIC-9') for p in chamadas))
        self.assertEqual(r.status, 'PROPOSTA_COM_PENDENCIAS')

    def test_base_so_e_consultada_depois_de_resolver_marca_e_cargo(self):
        enviados = []
        def response(q):
            enviados.append(q.url.path)
            if q.url.path.endswith('/marcas'):
                return httpx.Response(200, json={'encontrado': True, 'itens': [{'codigo': 10, 'descricao': 'PRETO'}]})
            if q.url.path.endswith('/cargos'):
                return httpx.Response(200, json={'encontrado': True, 'itens': [{'codigo': 100, 'descricao': 'VENDEDOR LOJA'}]})
            return httpx.Response(200, json={'encontrado': True, 'taxa': '0.03', 'competenciaUsada': '2026-12'})
        client, _ = backend({'/marcas': response, '/cargos': response, '/bases': response})
        texto = 'Mais 1 ponto percentual para vendedores da marca PRETO em dezembro'
        ext = {'regras': [{'trecho_origem': texto, 'marca_raw': 'PRETO', 'cargo_raw': 'vendedores', 'operacao_raw': 'mais 1 ponto percentual'}], 'vigencia_inicio_raw': 'dezembro'}
        r = AgenteInterpretador(llm([], extracao=ext), criar_registry(client)).executar(req(texto=texto))
        self.assertEqual([e.ferramenta for e in r.trilhaFerramentas], ['resolver_publico', 'consultar_base_comissao'])
        self.assertTrue(enviados[-1].endswith('/bases'))
        self.assertEqual(r.propostas[0].referencias[-1].taxaBase, Decimal('0.03'))
        # O hook atual não calcula ajustes: consultar a base não inventa uma taxa final.
        self.assertIsNone(r.propostas[0].taxa)

    def test_falha_do_backend_continua_impeditiva_em_todos_os_blocos_reutilizados(self):
        client, chamadas = backend({'/regras-concorrentes': lambda q: httpx.Response(503)})
        trecho = '3% para a loja 75'
        ext = {'regras': [{'trecho_origem': trecho, 'taxa_raw': '3%', 'loja_raw': '75'}] * 3, 'vigencia_inicio_raw': 'dezembro'}
        provider = llm([], extracao=ext)
        r = AgenteInterpretador(provider, criar_registry(client)).executar(req(texto=trecho + ' em dezembro'))
        self.assertEqual(len(chamadas), 2)  # uma consulta e a retentativa de infraestrutura já existente
        self.assertTrue(all('TOOL_FALHA' in cod(p) for p in r.propostas))
        self.assertTrue(all(e.status == 'FALHA' for e in r.trilhaFerramentas))
        self.assertEqual(provider.complete.call_count, 1)

    def test_sem_cadastro_nao_vira_publico_generico_apos_falha(self):
        client, _ = backend({'/cargos': lambda q: httpx.Response(503)})
        trecho = '3% para astronautas'
        ext = {'regras': [{'trecho_origem': trecho, 'taxa_raw': '3%', 'cargo_raw': 'astronautas'}], 'vigencia_inicio_raw': 'dezembro'}
        r = AgenteInterpretador(llm([], extracao=ext), criar_registry(client)).executar(req(texto=trecho + ' em dezembro'))
        self.assertIn('TOOL_FALHA', cod(r.propostas[0]))
        self.assertIsNone(r.propostas[0].condicoes.codCargo)
        self.assertNotEqual(r.status, 'PROPOSTA_COMPLETA')

    def test_edicao_mantem_id_da_campanha_ignorada(self):
        enviados = []
        def conc(q):
            enviados.append(json.loads(q.content))
            return httpx.Response(200, json={'conflitos': []})
        client, _ = backend({'/regras-concorrentes': conc})
        trecho = '3% para a loja 75'
        ext = {'regras': [{'trecho_origem': trecho, 'taxa_raw': '3%', 'loja_raw': '75'}], 'vigencia_inicio_raw': 'dezembro'}
        ctx = ContextoProposta(campanhaId='42', origem='VERSAO_EXISTENTE', substituiVersao='42')
        AgenteInterpretador(llm([], extracao=ext), criar_registry(client)).executar(req(texto=trecho + ' em dezembro', contexto=ctx))
        self.assertEqual(enviados[0]['ignorarCampanhaId'], '42')

    def test_429_na_extracao_propaga_sem_consultas_ou_propostas_ficticias(self):
        client, chamadas = backend()
        provider = llm([]); provider.complete.side_effect = LLMRateLimitError(retry_after_seconds=20)
        with self.assertRaises(LLMRateLimitError):
            AgenteInterpretador(provider, criar_registry(client)).executar(req())
        self.assertEqual(chamadas, [])
        self.assertEqual(provider.complete.call_count, 1)

    def test_limite_de_tempo_preserva_todos_os_blocos_e_consultas_nao_feitas(self):
        client, chamadas = backend()
        tick = {'value': 0}
        def clock():
            tick['value'] += 10
            return tick['value']
        r = AgenteInterpretador(llm([]), criar_registry(client), limites=Limites(max_duration_seconds=5), relogio=clock).executar(req())
        self.assertEqual(chamadas, [])
        self.assertEqual(len(r.propostas), 2)
        self.assertTrue(all('LIMITE_AGENTE_ATINGIDO' in cod(p) for p in r.propostas))


if __name__ == '__main__':
    unittest.main()
