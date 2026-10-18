"""
Serviço de simulação (requisito do cliente).

Fluxo: propostas → cenários (montados pelo agente a partir do pedido) → dados do Spring →
template (casos genéricos) OU código livre (casos complexos) → sandbox → validação do resultado.

Regras que não se negociam:
- o resultado é sempre SIMULAÇÃO, nunca apuração oficial;
- sem validação do resultado (§7.9.7) NENHUM número é devolvido;
- código livre vem sempre acompanhado do código executado e das premissas;
- a escolha template x código livre é determinística sobre `calculo_adicional`.
"""

import hashlib
import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from pydantic import ValidationError

from app.core.agente.limites import Limites
from app.core.config import settings
from app.core.exceptions import LLMAuthenticationError, LLMBaseException
from app.core.llm_retry import completar_com_retry
from app.core.pendencias import pendencia
from app.core.prompts.simulacao_prompt import (
    CenariosPedido,
    CodigoGerado,
    montar_prompt_cenarios,
    montar_prompt_codigo,
)
from app.core.simulacao.sandbox import ResultadoSandbox, Sandbox
from app.core.simulacao.templates import TEMPLATE_CODIGO
from app.providers.base import LLMProvider
from app.schemas.proposta import (
    BlocoProposta,
    Cenario,
    CodigoPendencia,
    EvidenciaTool,
    Pendencia,
    ResultadoCenario,
    SimularRequest,
    SimularResponse,
)
from app.tools.base import ToolRegistry

logger = logging.getLogger(__name__)

CENT = Decimal("0.01")
CENARIOS_PADRAO = [
    Cenario(nome="Vendas 80%", multiplicadorVendas=Decimal("0.8")),
    Cenario(nome="Vendas 100%", multiplicadorVendas=Decimal("1")),
    Cenario(nome="Vendas 120%", multiplicadorVendas=Decimal("1.2")),
]
_CHAVES = ("cenario", "totalVendas", "totalComissao", "porBloco", "porMatricula")

ESQUEMA_DADOS = {
    "vendas": {"id": "str", "matricula": "str", "codLoja": "int", "codMarca": "int", "codCargo": "int",
               "valorVenda": "Decimal", "dataVenda": "YYYY-MM-DD", "canal": "str|None"},
    "regras": {"idLocal": "str", "taxa": "Decimal|None", "bonus": "{percentual, valorFixo}|None",
               "dataInicio": "YYYY-MM-DD|None", "dataFim": "YYYY-MM-DD|None",
               "condicoes": "{canal, codMarca, codCargo, codLoja, matricula, faixaValor{min,max,minInclusivo,maxInclusivo}}"},
}
AMOSTRA_SINTETICA = {
    "vendas": [
        {"id": "s1", "matricula": "SIM-1", "codLoja": 1, "codMarca": 10, "codCargo": 100,
         "valorVenda": "1000.00", "dataVenda": "2026-01-10", "canal": None},
        {"id": "s2", "matricula": "SIM-2", "codLoja": 1, "codMarca": 10, "codCargo": 150,
         "valorVenda": "2500.50", "dataVenda": "2026-01-11", "canal": "ECOMMERCE"},
        {"id": "s3", "matricula": "SIM-1", "codLoja": 2, "codMarca": 20, "codCargo": 100,
         "valorVenda": "99.99", "dataVenda": "2026-01-12", "canal": None},
    ],
}


@dataclass
class _Falha:
    codigo: CodigoPendencia
    mensagem: str


class ServicoSimulacao:
    def __init__(
        self,
        provider: LLMProvider,
        tools: ToolRegistry,
        sandbox: Sandbox | None = None,
        limites: Limites | None = None,
    ) -> None:
        self._provider = provider
        self._tools = tools
        self._sandbox = sandbox or Sandbox()
        self._limites = limites or Limites()
        self._execucoes = 0
        self._trilha: list[EvidenciaTool] = []

    # ------------------------------------------------------------------ público
    def simular(self, request: SimularRequest) -> SimularResponse:
        self._execucoes = 0
        self._trilha = []
        observacoes: list[str] = []

        simulaveis, pend = self._propostas_simulaveis(request.propostas)
        if not simulaveis:
            return self._resposta_sem_numeros("TEMPLATE", pend or [pendencia(
                CodigoPendencia.CAMPO_AUSENTE, "Nenhuma proposta com taxa ou bônus para simular.")])

        cenarios, calculo_adicional = self._cenarios(request, observacoes)

        dados = self._dados(request)
        if isinstance(dados, _Falha):
            return self._resposta_sem_numeros("TEMPLATE", pend + [pendencia(dados.codigo, dados.mensagem)])
        vendas_sb, vendas_total = dados

        regras_sb = [_regra_para_sandbox(b) for b in simulaveis]
        cen_sb = [{"nome": c.nome, "multiplicadorVendas": str(c.multiplicadorVendas)} for c in cenarios]

        if calculo_adicional:
            return self._caminho_livre(
                calculo_adicional, simulaveis, regras_sb, vendas_sb, cen_sb, cenarios, observacoes, pend
            )
        return self._caminho_template(simulaveis, regras_sb, vendas_sb, cen_sb, cenarios, observacoes, pend)

    # ---------------------------------------------------------------- preparação
    def _propostas_simulaveis(self, propostas: list[BlocoProposta]) -> tuple[list[BlocoProposta], list[Pendencia]]:
        ok: list[BlocoProposta] = []
        pend: list[Pendencia] = []
        for b in propostas:
            if b.taxa is None and b.bonus is None:
                pend.append(pendencia(
                    CodigoPendencia.CAMPO_AUSENTE,
                    f"A proposta {b.idLocal} não tem taxa nem bônus definidos e não foi simulada.", "taxa"))
            else:
                ok.append(b)
        return ok, pend

    def _cenarios(self, request: SimularRequest, obs: list[str]) -> tuple[list[Cenario], str | None]:
        cenarios = list(request.cenarios)
        calculo_adicional: str | None = None
        if not cenarios and request.pedido and request.pedido.strip():
            try:
                bruto = completar_com_retry(
                    self._provider, montar_prompt_cenarios(request.pedido), CenariosPedido.model_json_schema()
                )
                extraido = CenariosPedido.model_validate(bruto)
                for c in extraido.cenarios:
                    try:
                        cenarios.append(Cenario(nome=str(c.get("nome", "Cenário")),
                                                multiplicadorVendas=Decimal(str(c.get("multiplicadorVendas", 1)))))
                    except (ValidationError, InvalidOperation):
                        obs.append(f"Cenário ignorado por ser inválido: {c}")
                calculo_adicional = (extraido.calculo_adicional or "").strip() or None
            except LLMAuthenticationError:
                raise
            except (LLMBaseException, ValidationError) as exc:
                obs.append("Não foi possível interpretar o pedido; usados os cenários padrão.")
                logger.warning("Extração de cenários falhou: %s", exc)
        if not cenarios:
            cenarios = list(CENARIOS_PADRAO)
            obs.append("Cenários padrão aplicados: 80%, 100% e 120% das vendas.")
        if len(cenarios) > settings.sim_max_cenarios:
            obs.append(f"Limite de {settings.sim_max_cenarios} cenários: os demais foram ignorados.")
            cenarios = cenarios[: settings.sim_max_cenarios]
        return cenarios, calculo_adicional

    def _dados(self, request: SimularRequest) -> tuple[list[dict[str, Any]], int] | _Falha:
        tool = self._tools.obter("obter_dados_simulacao")
        if tool is None:
            return _Falha(CodigoPendencia.TOOL_FALHA, "A consulta de dados da simulação não está disponível.")
        argumentos = {"competencia": request.competencia, **{
            k: v for k, v in request.filtro.items() if k in ("marca", "loja", "cargo", "matricula")}}
        r = tool.executar_dict(argumentos)
        self._trilha.append(EvidenciaTool(
            ferramenta="obter_dados_simulacao", argumentos=argumentos, status=r.status,
            resumo=(f"{r.dados['total']} vendas" if r.status == "OK" and r.dados else
                    (r.erro.tipo if r.erro else r.status))))
        if r.status == "FALHA":
            return _Falha(CodigoPendencia.TOOL_FALHA,
                          f"Não foi possível obter os dados da simulação ({r.erro.tipo if r.erro else 'erro'}).")
        if r.status == "SEM_DADOS" or not r.dados:
            return _Falha(CodigoPendencia.CAMPO_AUSENTE, "Não há vendas na competência informada para simular.")
        vendas = [_venda_para_sandbox(v) for v in r.dados["vendas"]]
        return vendas, len(vendas)

    # ------------------------------------------------------------------- caminhos
    def _caminho_template(self, simulaveis, regras_sb, vendas_sb, cen_sb, cenarios, obs, pend) -> SimularResponse:
        res = self._executar(TEMPLATE_CODIGO, "TEMPLATE", vendas_sb, regras_sb, cen_sb)
        if not res.ok:
            return self._resposta_sem_numeros("TEMPLATE", pend + [_pend_execucao(res)])
        resultados, falha = _validar_resultados(res.resultados, cenarios, simulaveis)
        if falha:
            return self._resposta_sem_numeros("TEMPLATE", pend + [pendencia(falha.codigo, falha.mensagem)])
        obs.append("Simulação por modelo padrão de cálculo (taxa, faixas e bônus por venda).")
        primeiro = res.resultados[0]
        if primeiro.get("vendasSemRegra"):
            obs.append(f"{primeiro['vendasSemRegra']} venda(s) não casaram com nenhuma proposta e ficaram fora do cálculo.")
        if primeiro.get("vendasEmConflito"):
            obs.append(f"{primeiro['vendasEmConflito']} venda(s) com propostas empatadas em especificidade "
                       "não foram calculadas (conflito).")
        return SimularResponse(origem="TEMPLATE", resultados=resultados, observacoes=obs, pendencias=pend,
                               trilhaFerramentas=self._trilha)

    def _caminho_livre(self, calculo, simulaveis, regras_sb, vendas_sb, cen_sb, cenarios, obs, pend) -> SimularResponse:
        gerado, falha = self._gerar_e_sondar(calculo, simulaveis, regras_sb, cenarios)
        if falha or gerado is None:
            assert falha is not None
            return self._resposta_sem_numeros("CODIGO_LIVRE", pend + [pendencia(falha.codigo, falha.mensagem)])
        codigo, premissas = gerado

        res = self._executar(codigo, "CODIGO_LIVRE", vendas_sb, regras_sb, cen_sb)
        if not res.ok:
            return self._resposta_sem_numeros("CODIGO_LIVRE", pend + [_pend_execucao(res)], codigo, premissas)
        resultados, falha = _validar_resultados(res.resultados, cenarios, simulaveis)
        if falha:
            return self._resposta_sem_numeros("CODIGO_LIVRE", pend + [pendencia(falha.codigo, falha.mensagem)],
                                              codigo, premissas)

        # teste diferencial interno: o total de vendas não depende da regra e o template o calcula
        ref = self._executar(TEMPLATE_CODIGO, "TEMPLATE", vendas_sb, regras_sb, cen_sb)
        if ref.ok:
            for rc, rr in zip(resultados, ref.resultados):
                if Decimal(str(rr["totalVendas"])) != rc.totalVendas:
                    return self._resposta_sem_numeros(
                        "CODIGO_LIVRE",
                        pend + [pendencia(CodigoPendencia.SIMULACAO_NAO_VALIDADA,
                                          "O total de vendas calculado pelo código gerado diverge do cálculo "
                                          "de referência; o resultado foi descartado.")],
                        codigo, premissas)
        obs.append("Resultado de código gerado pela IA; revise o código e as premissas antes de usar.")
        return SimularResponse(origem="CODIGO_LIVRE", resultados=resultados, observacoes=obs + premissas,
                               codigoExecutado=codigo, pendencias=pend, trilhaFerramentas=self._trilha)

    # --------------------------------------------------------------- código livre
    def _gerar_e_sondar(
        self, calculo: str, simulaveis: list[BlocoProposta], regras_sb: list[dict], cenarios: list[Cenario]
    ) -> tuple[tuple[str, list[str]] | None, _Falha | None]:
        """Gera o código (1 regeração se a análise rejeitar) e o prova numa execução-sonda sintética."""
        prompt = montar_prompt_codigo(calculo, ESQUEMA_DADOS, AMOSTRA_SINTETICA)
        ultimo_erro = ""
        for tentativa in (1, 2):
            if self._execucoes >= self._limites.max_code_executions:
                return None, _Falha(CodigoPendencia.LIMITE_AGENTE_ATINGIDO,
                                    "Limite de execuções de código atingido antes de validar o cálculo.")
            p = prompt if not ultimo_erro else prompt + f"\n\nA versão anterior foi REJEITADA: {ultimo_erro}\nCorrija."
            try:
                bruto = completar_com_retry(self._provider, p, CodigoGerado.model_json_schema())
                gerado = CodigoGerado.model_validate(bruto)
            except LLMAuthenticationError:
                raise
            except (LLMBaseException, ValidationError) as exc:
                logger.warning("Geração de código falhou: %s", exc)
                return None, _Falha(CodigoPendencia.SIMULACAO_NAO_VALIDADA,
                                    "Não foi possível gerar o código da simulação.")
            sonda = self._executar(
                gerado.codigo, "CODIGO_LIVRE(sonda)", AMOSTRA_SINTETICA["vendas"], regras_sb,
                [{"nome": "sonda", "multiplicadorVendas": "1"}],
            )
            if not sonda.ok:
                ultimo_erro = f"{sonda.erro}: {sonda.detalhe}"
                if sonda.erro == "VALIDACAO" and tentativa == 1:
                    continue  # regenera uma vez com a violação apontada
                return None, _Falha(CodigoPendencia.SIMULACAO_NAO_VALIDADA,
                                    f"O código gerado foi rejeitado ({ultimo_erro}); nenhum número é exibido.")
            _, falha = _validar_resultados(sonda.resultados, [Cenario(nome="sonda")], simulaveis)
            if falha:
                return None, _Falha(CodigoPendencia.SIMULACAO_NAO_VALIDADA,
                                    f"O código gerado não passou na validação de sondagem: {falha.mensagem}")
            return (gerado.codigo, gerado.premissas), None
        return None, _Falha(CodigoPendencia.SIMULACAO_NAO_VALIDADA, "Não foi possível obter código válido.")

    # ---------------------------------------------------------------- execução
    def _executar(self, codigo: str, origem: str, vendas, regras, cenarios) -> ResultadoSandbox:
        self._execucoes += 1
        res = self._sandbox.executar(codigo, vendas, regras, cenarios)
        self._trilha.append(EvidenciaTool(
            ferramenta="executar_codigo",
            argumentos={"origem": origem, "hashCodigo": hashlib.sha256(codigo.encode()).hexdigest()[:12],
                        "linhas": len(codigo.splitlines()), "registros": len(vendas)},
            status="OK" if res.ok else "FALHA",
            resumo="ok" if res.ok else f"{res.erro}: {res.detalhe}"[:200],
        ))
        return res

    def _resposta_sem_numeros(self, origem: str, pend: list[Pendencia], codigo: str | None = None,
                              premissas: list[str] | None = None) -> SimularResponse:
        return SimularResponse(origem=origem, resultados=[], pendencias=pend, codigoExecutado=codigo,
                               observacoes=premissas or [], trilhaFerramentas=self._trilha)


# --------------------------------------------------------------------- helpers
def _pend_execucao(res: ResultadoSandbox) -> Pendencia:
    return pendencia(
        CodigoPendencia.SIMULACAO_NAO_VALIDADA,
        f"A execução da simulação foi bloqueada ou falhou ({res.erro}: {res.detalhe}); nenhum número é exibido.",
    )


def _venda_para_sandbox(v: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(v.get("id", "")),
        "matricula": v.get("matricula"),
        "codLoja": v.get("codLoja"),
        "codMarca": v.get("codMarca"),
        "codCargo": v.get("codCargo"),
        "valorVenda": str(v.get("valorVenda", "0")),
        "dataVenda": str(v.get("dataVenda")) if v.get("dataVenda") else None,
        "canal": v.get("canal"),
    }


def _regra_para_sandbox(b: BlocoProposta) -> dict[str, Any]:
    c = b.condicoes
    faixa = None
    if c.faixaValor:
        f = c.faixaValor
        faixa = {"min": str(f.min) if f.min is not None else None,
                 "max": str(f.max) if f.max is not None else None,
                 "minInclusivo": f.minInclusivo, "maxInclusivo": f.maxInclusivo}
    bonus = None
    if b.bonus:
        bonus = {"percentual": str(b.bonus.percentual) if b.bonus.percentual is not None else None,
                 "valorFixo": str(b.bonus.valorFixo) if b.bonus.valorFixo is not None else None}
    return {
        "idLocal": b.idLocal,
        "taxa": str(b.taxa) if b.taxa is not None else None,
        "bonus": bonus,
        "dataInicio": b.dataInicio.isoformat() if b.dataInicio else None,
        "dataFim": b.dataFim.isoformat() if b.dataFim else None,
        "condicoes": {"canal": c.canal, "codMarca": c.codMarca, "codCargo": c.codCargo, "codLoja": c.codLoja,
                      "matricula": c.matricula, "faixaValor": faixa},
    }


def _dec(valor: Any) -> Decimal:
    d = Decimal(str(valor))
    if not d.is_finite():
        raise InvalidOperation("não finito")
    return d


def _validar_resultados(
    resultados: list[dict[str, Any]], cenarios: list[Cenario], simulaveis: list[BlocoProposta]
) -> tuple[list[ResultadoCenario], _Falha | None]:
    """Validação do §7.9.7: formato, escala monetária, invariantes e coerência das partes."""

    def falha(msg: str) -> tuple[list[ResultadoCenario], _Falha]:
        return [], _Falha(CodigoPendencia.SIMULACAO_NAO_VALIDADA, f"Resultado inválido: {msg}")

    if len(resultados) != len(cenarios):
        return falha("quantidade de cenários diferente da esperada.")
    ids = {b.idLocal for b in simulaveis}
    tem_bonus_fixo = any(b.bonus and b.bonus.valorFixo is not None for b in simulaveis)
    saida: list[ResultadoCenario] = []
    for r in resultados:
        if not isinstance(r, dict) or any(k not in r for k in _CHAVES):
            return falha(f"faltam chaves obrigatórias ({', '.join(_CHAVES)}).")
        try:
            tv, tc = _dec(r["totalVendas"]), _dec(r["totalComissao"])
            por_bloco = {str(k): _dec(v) for k, v in dict(r["porBloco"]).items()}
            por_mat = {str(k): _dec(v) for k, v in dict(r["porMatricula"]).items()}
        except (InvalidOperation, ValueError, TypeError):
            return falha("valores não numéricos ou não finitos.")
        for v in [tv, tc, *por_bloco.values(), *por_mat.values()]:
            if v != v.quantize(CENT, rounding=ROUND_HALF_UP):
                return falha("valor monetário fora da escala de 2 casas decimais.")
            if v < 0:
                return falha("valor monetário negativo.")
        if not set(por_bloco) <= ids:
            return falha("o resultado cita propostas inexistentes.")
        if sum(por_bloco.values(), Decimal("0")) != tc:
            return falha("a soma por proposta não confere com o total de comissão.")
        if sum(por_mat.values(), Decimal("0")) != tc:
            return falha("a soma por matrícula não confere com o total de comissão.")
        if not tem_bonus_fixo and tc > tv:
            return falha("a comissão total excede o total de vendas.")
        saida.append(ResultadoCenario(cenario=str(r["cenario"]), totalVendas=tv, totalComissao=tc,
                                      porBloco=por_bloco, porMatricula=por_mat))
    return saida, None
