"""
Detecção estatística diária de anomalias (IA-8 / BUG-121).

Fluxo: agregar por colaborador/dia em grupos comparáveis -> IQR por grupo -> alertas fora da faixa.
Determinístico e sem LLM. Uma anomalia é INDÍCIO para conferir, nunca correção da venda:
o serviço não altera nem exclui vendas, só aponta o que olhar e por quê.

Proteções contra alertas artificiais:
- grupo com menos observações que `amostraMinima` -> AMOSTRA_INSUFICIENTE (sem alerta);
- IQR = 0 (valores repetidos) -> SEM_VARIACAO (sem alerta: qualquer diferença viraria "anomalia");
- dia sem venda não é observação de valor zero;
- vendas sem RH/cargo, sem marca ou fora da competência são erros de carga, fora da análise.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from decimal import Decimal

from app.core.anomalias.agregador import LIMITE_IDS, ChaveGrupo, Observacao, agregar, versao_dados
from app.core.anomalias.iqr import Faixa, faixa_iqr
from app.core.config import settings
from app.schemas.anomalia import (
    AlertaAnomalia,
    AnalisarAnomaliasRequest,
    AnalisarAnomaliasResponse,
    CoberturaDias,
    ErroCarga,
    EvidenciaIqr,
    FaixaEsperada,
    GrupoComparavel,
    MetodoAnomalia,
    ResultadoGrupo,
    ResumoAnomalias,
    VendaAnomalia,
)

_MOTIVOS_ERRO = {
    "VENDA_SEM_RH": "Venda sem colaborador no RH da competência (ou sem cargo): não há grupo para comparar.",
    "VENDA_SEM_MARCA": "Venda sem código de marca: não há grupo para comparar.",
    "FORA_DA_COMPETENCIA": "Data da venda fora da competência analisada.",
}


class VolumeExcedido(ValueError):
    pass


def analisar(request: AnalisarAnomaliasRequest) -> AnalisarAnomaliasResponse:
    if len(request.vendas) > settings.anomalia_max_vendas:
        raise VolumeExcedido(f"O recorte tem {len(request.vendas)} vendas; o limite da análise é "
                             f"{settings.anomalia_max_vendas}.")
    k = request.parametros.k if request.parametros.k is not None else Decimal(str(settings.anomalia_k))
    minimo = request.parametros.amostraMinima or settings.anomalia_amostra_minima
    comp = request.competencia
    versao = versao_dados(request.vendas, request.dadosRh, comp, k, minimo)

    ag = agregar(request.vendas, request.dadosRh, comp)
    grupos: list[ResultadoGrupo] = []
    alertas: list[AlertaAnomalia] = []
    for chave in sorted(ag.grupos, key=lambda c: (c[0], c[1], c[2] or "")):
        resultado, novos = _avaliar_grupo(chave, ag.grupos[chave], comp, k, minimo, versao)
        grupos.append(resultado)
        alertas.extend(novos)

    erros = [_erro(codigo, vendas) for codigo, vendas in sorted(ag.erros.items())]
    resumo = ResumoAnomalias(
        totalVendas=len(request.vendas),
        vendasAnalisadas=ag.vendas_analisadas,
        observacoes=sum(g.tamanhoAmostra for g in grupos),
        grupos=len(grupos),
        gruposAnalisados=sum(g.status == "ANALISADO" for g in grupos),
        gruposAmostraInsuficiente=sum(g.status == "AMOSTRA_INSUFICIENTE" for g in grupos),
        gruposSemVariacao=sum(g.status == "SEM_VARIACAO" for g in grupos),
        alertas=len(alertas),
        vendasComErroCarga=sum(e.quantidade for e in erros),
    )
    cobertura = CoberturaDias(diasNaCompetencia=ag.dias_na_competencia, diasComVenda=ag.dias_com_venda,
                              diasSemCobertura=ag.dias_na_competencia - len(ag.dias_com_venda))
    return AnalisarAnomaliasResponse(
        execucaoId=request.contexto.execucaoId,
        contexto=request.contexto,
        competencia=comp,
        metodo=MetodoAnomalia(k=k, amostraMinima=minimo),
        versaoDados=versao,
        versaoFontes=request.versaoFontes,
        resumo=resumo,
        alertas=alertas,
        grupos=grupos,
        errosCarga=erros,
        cobertura=cobertura,
        observacoes=_observacoes(ag.dias_com_venda, cobertura),
        explicacao=_explicacao(resumo, minimo),
    )


def _avaliar_grupo(chave: ChaveGrupo, obs: list[Observacao], comp: str, k: Decimal, minimo: int,
                   versao: str) -> tuple[ResultadoGrupo, list[AlertaAnomalia]]:
    grupo = GrupoComparavel(codMarca=chave[0], codCargo=chave[1], descriCargo=chave[2], competencia=comp)
    base = {"grupo": grupo, "tamanhoAmostra": len(obs), "colaboradores": len({o.matricula for o in obs})}
    if len(obs) < minimo:
        return ResultadoGrupo(**base, status="AMOSTRA_INSUFICIENTE",
                              motivo=f"{len(obs)} observação(ões) colaborador/dia; mínimo para avaliar: {minimo}."), []
    valores = [o.valor for o in obs]
    f = faixa_iqr(valores, k)
    if f.minimo < 0 <= min(valores):
        # Sem valores negativos no grupo, um limite inferior negativo não informa nada ao usuário.
        f = replace(f, minimo=Decimal("0.00"))
    evid = EvidenciaIqr(q1=f.q1, mediana=f.mediana, q3=f.q3, iqr=f.iqr)
    faixa = FaixaEsperada(min=f.minimo, max=f.maximo)
    if f.iqr == 0:
        return ResultadoGrupo(**base, status="SEM_VARIACAO", evidencia=evid, faixaEsperada=faixa,
                              motivo="Q1 = Q3 (valores repetidos): sem dispersão para definir anomalia."), []
    alertas = [_alerta(o, grupo, f, evid, faixa, len(obs), versao) for o in obs
               if o.valor > f.maximo or o.valor < f.minimo]
    alertas.sort(key=lambda a: (-a.distanciaFaixa, a.matricula, a.data))
    return ResultadoGrupo(**base, status="ANALISADO", evidencia=evid, faixaEsperada=faixa,
                          qtdAlertas=len(alertas)), alertas


def _alerta(o: Observacao, grupo: GrupoComparavel, f: Faixa, evid: EvidenciaIqr, faixa: FaixaEsperada,
            n: int, versao: str) -> AlertaAnomalia:
    acima = o.valor > f.maximo
    distancia = o.valor - f.maximo if acima else f.minimo - o.valor
    descr = f" ({grupo.descriCargo})" if grupo.descriCargo else ""
    explicacao = (
        f"A matrícula {o.matricula} somou {_brl(o.valor)} em {len(o.venda_ids)} venda(s) no dia "
        f"{o.data:%d/%m/%Y}, {'acima' if acima else 'abaixo'} da faixa esperada para marca {grupo.codMarca}, "
        f"cargo {grupo.codCargo}{descr} ({_brl(f.minimo)} a {_brl(f.maximo)}; Q1 {_brl(f.q1)}, "
        f"mediana {_brl(f.mediana)}, Q3 {_brl(f.q3)}, {n} observações). "
        "Conferir as vendas desse dia na origem; o alerta não altera nem corrige a venda."
    )
    chave = f"{versao}|{grupo.codMarca}|{grupo.codCargo}|{grupo.descriCargo}|{o.matricula}|{o.data.isoformat()}"
    return AlertaAnomalia(
        id=hashlib.sha256(chave.encode("utf-8")).hexdigest()[:20],
        tipo="ACIMA_DA_FAIXA" if acima else "ABAIXO_DA_FAIXA",
        matricula=o.matricula, data=o.data, valorObservado=o.valor, qtdVendas=len(o.venda_ids),
        vendaIds=o.venda_ids[:LIMITE_IDS], faixaEsperada=faixa, distanciaFaixa=distancia, grupo=grupo,
        tamanhoAmostra=n, evidencia=evid, explicacao=explicacao,
    )


def _erro(codigo: str, vendas: list[VendaAnomalia]) -> ErroCarga:
    mats = sorted({v.matricula for v in vendas if v.matricula})
    return ErroCarga(codigo=codigo, motivo=_MOTIVOS_ERRO[codigo], quantidade=len(vendas),  # type: ignore[arg-type]
                     valorVendas=sum((v.valorVenda for v in vendas), Decimal("0")),
                     matriculas=mats[:LIMITE_IDS], vendaIds=sorted(v.id for v in vendas)[:LIMITE_IDS])


def _observacoes(dias: list, cobertura: CoberturaDias) -> list[str]:
    obs: list[str] = []
    if len(dias) == 1:
        obs.append(f"Todas as vendas analisadas estão registradas em {dias[0]:%d/%m/%Y}: nesta base, o total "
                   "colaborador/dia coincide com o total do colaborador na competência.")
    if cobertura.diasSemCobertura:
        obs.append(f"{cobertura.diasSemCobertura} dia(s) da competência sem nenhuma venda no recorte não foram "
                   "tratados como venda zero.")
    return obs


def _explicacao(r: ResumoAnomalias, minimo: int) -> str:
    partes = [f"Foram analisadas {r.vendasAnalisadas} de {r.totalVendas} venda(s), agregadas em "
              f"{r.observacoes} total(is) colaborador/dia e comparadas dentro de {r.grupos} grupo(s) "
              "de mesma marca e cargo."]
    if r.alertas:
        partes.append(f"{r.alertas} total(is) ficaram fora da faixa esperada do grupo (IQR) e devem ser conferidos.")
    else:
        partes.append("Nenhum total ficou fora da faixa esperada do grupo.")
    if r.gruposAmostraInsuficiente:
        partes.append(f"{r.gruposAmostraInsuficiente} grupo(s) com menos de {minimo} observações não foram "
                      "avaliados (amostra insuficiente).")
    if r.gruposSemVariacao:
        partes.append(f"{r.gruposSemVariacao} grupo(s) sem variação (Q1 = Q3) não geram alerta.")
    if r.vendasComErroCarga:
        partes.append(f"{r.vendasComErroCarga} venda(s) com erro de carga ficaram fora da análise.")
    partes.append("Nenhuma venda foi alterada: os alertas são indícios para conferência.")
    return " ".join(partes)


def _brl(valor: Decimal) -> str:
    sinal = "-" if valor < 0 else ""
    return f"{sinal}R$ " + f"{abs(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
