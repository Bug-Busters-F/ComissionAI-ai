"""
Serviço de reinterpretação localizada de regras (IA-6 / BUG-57).

Recebe o texto alterado de uma regra com seu contexto, preservando os demais
blocos e identificando campos alterados e eventual subdivisão de regras.
"""

from decimal import Decimal

from app.core.agente import AgenteInterpretador
from app.core.pendencias import pendencia
from app.core.prompts.codigo_regra_prompt import gerar_codigo_regra
from app.schemas.proposta import (
    BlocoProposta,
    CodigoPendencia,
    FaixaValor,
    InterpretarRequestV2,
    ReinterpretarRequest,
    ReinterpretarResponse,
)


class RequisicaoReinterpretacao(InterpretarRequestV2):
    """Pedido interno ao agente: o texto alterado mais o bloco que ele substitui (contexto)."""

    blocoAtual: BlocoProposta | None = None


class ServicoReinterpretacao:
    """Gerencia a reinterpretação isolada de um bloco alterado."""

    def __init__(self, agente: AgenteInterpretador) -> None:
        self._agente = agente

    def reinterpretar(self, request: ReinterpretarRequest) -> ReinterpretarResponse:
        """
        Reinterpreta só o bloco `idLocal`; `demaisBlocos` são apenas lidos para checar conflitos.

        O que o texto alterado não cita (público, faixa, taxa) é herdado do bloco atual pelos hooks
        do agente; na edição de versão existente o agente ignora a própria campanha na concorrência.
        """
        atual = request.blocoAtual
        competencia = None
        if atual.dataInicio:
            competencia = atual.dataInicio.strftime("%Y-%m")
        elif request.vigenciaCampanha and request.vigenciaCampanha.inicio:
            competencia = request.vigenciaCampanha.inicio.strftime("%Y-%m")
        sub_req = RequisicaoReinterpretacao(
            texto=request.textoAlterado,
            contexto=request.contexto,
            vigenciaCampanha=request.vigenciaCampanha,
            dataReferencia=request.dataReferencia,
            competencia=competencia,
            catalogo=request.catalogo,
            blocoAtual=atual,
        )

        res_agente = self._agente.executar(sub_req)
        propostas = res_agente.propostas

        # 1 bloco: preserva o idLocal original; vários: o primeiro mantém, os demais recebem sufixo
        for i, p in enumerate(propostas, start=1):
            p.idLocal = request.idLocal if i == 1 else f"{request.idLocal}_{i}"
            if p.codigoPython is not None:
                p.codigoPython = gerar_codigo_regra(p)  # o idLocal faz parte do código gerado

        campos_alterados = self._detectar_campos_alterados(atual, propostas)
        self._checar_conflitos(propostas, request.demaisBlocos)

        return ReinterpretarResponse(
            contexto=request.contexto,
            propostasSubstituicao=propostas,
            camposAlterados=campos_alterados,
            pendenciasGerais=res_agente.pendenciasGerais,
        )

    def _detectar_campos_alterados(self, atual: BlocoProposta, substitutos: list[BlocoProposta]) -> list[str]:
        alterados: set[str] = set()
        for s in substitutos:
            for campo in ("taxa", "operacao", "bonus", "dataInicio", "dataFim"):
                if getattr(s, campo) != getattr(atual, campo):
                    alterados.add(campo)
            for campo in ("codCargo", "codMarca", "codLoja", "matricula", "canal", "faixaValor"):
                if getattr(s.condicoes, campo) != getattr(atual.condicoes, campo):
                    alterados.add(f"condicoes.{campo}")
        return sorted(alterados)

    def _checar_conflitos(self, novas: list[BlocoProposta], demais: list[BlocoProposta]) -> None:
        """
        Conflito = mesma especificidade com público, faixa e vigência sobrepostos: o motor não
        consegue escolher a regra e impede o cálculo. Sobreposição com especificidades diferentes
        é resolvida pela precedência e não gera pendência. Compara também os blocos da divisão.
        """
        for i, nova in enumerate(novas):
            outros = list(demais) + novas[i + 1:]
            for outro in outros:
                if _especificidade(nova) == _especificidade(outro) and _sobrepoem(nova, outro):
                    nova.pendencias.append(
                        pendencia(
                            CodigoPendencia.CONFLITO_REGRA,
                            f"A proposta reinterpretada tem o mesmo público, faixa e período da regra "
                            f"'{outro.idLocal}'; uma venda não teria regra vencedora.",
                            None,
                            "Ajuste o público ou a faixa de uma das regras, ou remova uma delas.",
                        )
                    )


_PESOS = (("matricula", 16), ("codLoja", 8), ("codCargo", 4), ("canal", 2), ("codMarca", 1))


def _especificidade(b: BlocoProposta) -> Decimal:
    """Mesmos pesos do motor (templates.py / Spring): matrícula 16, loja 8, cargo 4, canal 2, marca 1."""
    total = Decimal(sum(peso for campo, peso in _PESOS if getattr(b.condicoes, campo) is not None))
    return total + (Decimal("0.5") if b.condicoes.faixaValor is not None else 0)


def _sobrepoem(a: BlocoProposta, b: BlocoProposta) -> bool:
    if a.dataInicio and b.dataFim and a.dataInicio > b.dataFim:
        return False
    if a.dataFim and b.dataInicio and a.dataFim < b.dataInicio:
        return False
    ca, cb = a.condicoes, b.condicoes
    for campo, _ in _PESOS:
        va, vb = getattr(ca, campo), getattr(cb, campo)
        if campo == "canal" and va is not None and vb is not None:
            va, vb = va.upper(), vb.upper()
        if va is not None and vb is not None and va != vb:
            return False
    return _faixas_sobrepoem(ca.faixaValor, cb.faixaValor)


def _faixas_sobrepoem(fa: FaixaValor | None, fb: FaixaValor | None) -> bool:
    if fa is None or fb is None:
        return True
    return not (_termina_antes(fa, fb) or _termina_antes(fb, fa))


def _termina_antes(fa: FaixaValor, fb: FaixaValor) -> bool:
    """True se toda a faixa `fa` fica abaixo de `fb`."""
    if fa.max is None or fb.min is None:
        return False
    if fa.max < fb.min:
        return True
    return fa.max == fb.min and not (fa.maxInclusivo and fb.minInclusivo)
