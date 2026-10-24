"""
Geração de explicações rastreáveis por regra e por campo (IA-7 / BUG-58).

Determinística: só cita o que está na proposta (nenhuma chamada ao LLM, nada inferido).
Fontes rastreáveis:
- Trecho literal do pedido (origem.trecho)
- Base consultada (referência BASE_COMISS) e operação aplicada sobre ela
- Cadastros resolvidos (marca, cargo, loja)
- Vigência herdada da campanha ou definida no texto
- Edição manual pelo gestor (origem: MANUAL)
"""

from decimal import Decimal

from app.core.normalizers.taxa import descrever_operacao, formatar_percentual
from app.schemas.proposta import BlocoProposta, VigenciaCampanha


def gerar_explicacao_bloco(
    bloco: BlocoProposta,
    origem_campos: dict[str, str] | None = None,
    vigencia_campanha: VigenciaCampanha | None = None,
) -> str:
    """
    Gera uma explicação textual rastreável e objetiva para o bloco de proposta.

    Args:
        bloco: O bloco de proposta com seus campos preenchidos.
        origem_campos: Dicionário opcional mapeando campo -> 'MANUAL' | 'IA'.
        vigencia_campanha: Vigência comum da campanha, para indicar quando a regra a herdou.

    Returns:
        Texto explicativo detalhado e rastreável.
    """
    origens = origem_campos or {}
    partes: list[str] = []

    if bloco.origem and bloco.origem.trecho:
        partes.append(f"Origem: trecho \"{bloco.origem.trecho}\".")

    partes.append(_explicar_taxa(bloco, origens))

    publico = _explicar_publico(bloco, origens)
    if publico:
        partes.append(f"Aplicável para: {publico}.")
    else:
        partes.append("Aplicável a todas as vendas da vigência (nenhum filtro de público).")

    vigencia = _explicar_vigencia(bloco, origens, vigencia_campanha)
    if vigencia:
        partes.append(vigencia)

    if bloco.bonus:
        b = bloco.bonus
        bonus_partes: list[str] = []
        if b.percentual is not None:
            bonus_partes.append(f"{formatar_percentual(b.percentual)} adicional sobre o valor da venda")
        if b.valorFixo is not None:
            bonus_partes.append(f"{_reais(b.valorFixo)} fixo por venda")
        if bonus_partes:
            partes.append(f"Bônus: {' e '.join(bonus_partes)}{_marca_manual('bonus', origens)}.")

    partes.append(
        "Vendas fora destas condições não recebem esta regra: vale outra regra aplicável ou a base de comissão."
    )
    if bloco.pendencias:
        partes.append(f"Pendências em aberto: {len(bloco.pendencias)} (revise antes de simular).")
    return " ".join(partes)


def _explicar_taxa(bloco: BlocoProposta, origens: dict[str, str]) -> str:
    if origens.get("taxa") == "MANUAL":
        if bloco.taxa is None:
            return "Taxa removida na edição manual; informe a taxa desta regra (origem: MANUAL)."
        return f"Taxa de {formatar_percentual(bloco.taxa)} definida manualmente pelo gestor (origem: MANUAL)."

    op = bloco.operacao
    ajuste = op is not None and op.tipo != "TAXA_ABSOLUTA"
    ref_base = next((r for r in bloco.referencias if r.fonte == "BASE_COMISS" and r.taxaBase is not None), None)
    if ajuste and ref_base and bloco.taxa is not None:
        chave = ref_base.chave or {}
        detalhes = ", ".join(
            f"{rotulo} {chave[k]}"
            for k, rotulo in (("codMarca", "marca"), ("codCargo", "cargo"), ("competencia", "competência"))
            if chave.get(k) is not None
        )
        origem_base = f" ({detalhes})" if detalhes else ""
        return (
            f"Base de comissão consultada{origem_base}: {formatar_percentual(ref_base.taxaBase)}; "
            f"operação: {descrever_operacao(op.tipo, op.valor)}; "
            f"taxa final: {formatar_percentual(bloco.taxa)}."
        )
    if ajuste:
        return (
            f"Ajuste pedido ({descrever_operacao(op.tipo, op.valor)}) depende da base de comissão, "
            "que não pôde ser determinada; a taxa final está pendente."
        )
    if bloco.taxa is not None:
        if bloco.origem and bloco.origem.trecho:
            return f"Taxa de {formatar_percentual(bloco.taxa)} informada no trecho do pedido."
        return f"Taxa de {formatar_percentual(bloco.taxa)}."
    if bloco.bonus is not None:
        return "Sem taxa sobre a venda; a regra paga apenas o bônus."
    return "Taxa de comissão pendente de definição."


def _explicar_publico(bloco: BlocoProposta, origens: dict[str, str]) -> str:
    cond = bloco.condicoes
    itens: list[str] = []
    if cond.matricula is not None:
        itens.append(f"matrícula {cond.matricula}{_marca_manual('condicoes.matricula', origens)}")
    if cond.codLoja is not None:
        itens.append(f"loja {cond.codLoja}{_marca_manual('condicoes.codLoja', origens)}")
    if cond.codCargo is not None:
        nome = f"{cond.descriCargo} " if cond.descriCargo else ""
        itens.append(f"cargo {nome}(cód. {cond.codCargo}){_marca_manual('condicoes.codCargo', origens)}")
    if cond.canal is not None:
        itens.append(f"canal {cond.canal}{_marca_manual('condicoes.canal', origens)}")
    if cond.codMarca is not None:
        nome = f"{cond.descrMarca} " if cond.descrMarca else ""
        itens.append(f"marca {nome}(cód. {cond.codMarca}){_marca_manual('condicoes.codMarca', origens)}")
    if cond.faixaValor is not None:
        fv = cond.faixaValor
        limites: list[str] = []
        if fv.min is not None:
            limites.append(f"a partir de {_reais(fv.min)} ({'inclusive' if fv.minInclusivo else 'exclusive'})")
        if fv.max is not None:
            limites.append(f"até {_reais(fv.max)} ({'inclusive' if fv.maxInclusivo else 'exclusive'})")
        itens.append(f"vendas {' e '.join(limites)}{_marca_manual('condicoes.faixaValor', origens)}")
    return ", ".join(itens)


def _explicar_vigencia(
    bloco: BlocoProposta, origens: dict[str, str], vigencia_campanha: VigenciaCampanha | None
) -> str | None:
    if not bloco.dataInicio:
        return None
    if bloco.dataFim:
        texto = f"Vigência de {bloco.dataInicio:%d/%m/%Y} a {bloco.dataFim:%d/%m/%Y}"
    else:
        texto = f"Vigência a partir de {bloco.dataInicio:%d/%m/%Y}"
    if origens.get("dataInicio") == "MANUAL" or origens.get("dataFim") == "MANUAL":
        texto += " (edição manual)"
    elif vigencia_campanha and (vigencia_campanha.inicio, vigencia_campanha.fim) == (bloco.dataInicio, bloco.dataFim):
        texto += " (herdada da vigência da campanha)"
    return texto + "."


def _marca_manual(campo: str, origens: dict[str, str]) -> str:
    return " (edição manual)" if origens.get(campo) == "MANUAL" else ""


def _reais(valor: Decimal) -> str:
    inteiro, _, centavos = f"{valor:,.2f}".partition(".")
    return f"R$ {inteiro.replace(',', '.')},{centavos}"
