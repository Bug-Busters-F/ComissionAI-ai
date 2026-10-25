"""
Pontos de extensão do agente. Por padrão são identidade (no-op).

O Humberto (IA-5, IA-7, IA-9) pluga a lógica de ajustes sobre a base, explicação/código
e validações finais SEM alterar o laço. Mudou a assinatura => avisar no PR.
"""

from decimal import Decimal
from typing import Any, Protocol

from app.core.normalizers.taxa import (
    calcular_taxa_com_operacao,
    descrever_operacao,
    formatar_percentual,
    interpretar_operacao,
)
from app.core.pendencias import pendencia
from app.core.prompts.codigo_regra_prompt import gerar_codigo_regra
from app.core.prompts.explicacao_prompt import gerar_explicacao_bloco
from app.core.services.campanha import BlocoInterno
from app.schemas.proposta import BlocoProposta, CodigoPendencia, Operacao
from app.tools.base import ToolResult


class Hooks(Protocol):
    def pos_extracao(self, blocos: list[BlocoInterno], ctx: dict[str, Any]) -> list[BlocoInterno]: ...

    def pos_consulta(self, bloco: BlocoInterno, ferramenta: str, resultado: ToolResult) -> BlocoInterno: ...

    def antes_de_fechar(self, blocos: list[BlocoProposta], ctx: dict[str, Any]) -> list[BlocoProposta]: ...


class HooksPadrao:
    """No-op: devolve exatamente o que recebeu."""

    def pos_extracao(self, blocos: list[BlocoInterno], ctx: dict[str, Any]) -> list[BlocoInterno]:
        return blocos

    def pos_consulta(self, bloco: BlocoInterno, ferramenta: str, resultado: ToolResult) -> BlocoInterno:
        return bloco

    def antes_de_fechar(self, blocos: list[BlocoProposta], ctx: dict[str, Any]) -> list[BlocoProposta]:
        return blocos


class HooksAjusteSobreBase(HooksPadrao):
    """
    Hooks de produção do agente (IA-5, IA-6, IA-7).

    1. pos_extracao: na reinterpretação (IA-6), herda do bloco atual o que o texto alterado não cita;
       classifica as operações sobre a base (IA-5), sem presumir expressões ambíguas.
    2. pos_consulta: após consultar a base de comissão, calcula a taxa final, fixa-a na proposta e
       mantém a operação original para rastreabilidade (IA-5).
    3. antes_de_fechar: sinaliza ajustes cujo público abrange várias bases (IA-5) e gera explicação
       e Python a partir dos campos finais (IA-7).
    """

    def pos_extracao(self, blocos: list[BlocoInterno], ctx: dict[str, Any]) -> list[BlocoInterno]:
        """Herda o contexto do bloco reinterpretado e normaliza as operações sobre a base."""
        bloco_atual = getattr(ctx.get("request"), "blocoAtual", None)
        for b in blocos:
            if isinstance(bloco_atual, BlocoProposta):
                _herdar_do_bloco_atual(b, bloco_atual)
            _normalizar_operacao_do_bloco(b)
        return blocos

    def pos_consulta(self, bloco: BlocoInterno, ferramenta: str, resultado: ToolResult) -> BlocoInterno:
        """Calcula a taxa final quando a base de comissão foi encontrada."""
        if ferramenta != "consultar_base_comissao" or resultado.status != "OK":
            return bloco  # SEM_DADOS / AMBIGUO / FALHA já viram pendência no agente; nada é inventado
        bl = bloco.bloco
        dados = resultado.dados or {}
        if not bl.operacao or bl.operacao.tipo == "TAXA_ABSOLUTA" or "taxa" not in dados:
            return bloco

        taxa_base = Decimal(str(dados["taxa"]))
        taxa_final = calcular_taxa_com_operacao(taxa_base, bl.operacao.tipo, bl.operacao.valor)
        operacao_txt = descrever_operacao(bl.operacao.tipo, bl.operacao.valor)
        if taxa_final <= Decimal("0") or taxa_final > Decimal("1.0000"):
            bl.pendencias.append(
                pendencia(
                    CodigoPendencia.TAXA_INVALIDA,
                    f"A base {formatar_percentual(taxa_base)} com {operacao_txt} resulta em "
                    f"{formatar_percentual(taxa_final)}, fora do intervalo permitido (0% a 100%].",
                    "taxa",
                    "Informe a taxa final desejada para esta regra.",
                )
            )
            return bloco

        # taxa final fixada; a operação original (tipo + delta) e a base consultada continuam rastreáveis
        bl.taxa = taxa_final
        bl.pendencias = [
            p for p in bl.pendencias if not (p.codigo == CodigoPendencia.CAMPO_AUSENTE and p.campo == "taxa")
        ]
        return bloco

    def antes_de_fechar(self, blocos: list[BlocoProposta], ctx: dict[str, Any]) -> list[BlocoProposta]:
        """IA-5: pendência para ajuste sem base única; IA-7: explicação e código sincronizados."""
        request = ctx.get("request")
        vigencia = getattr(request, "vigenciaCampanha", None)
        for b in blocos:
            _sinalizar_publico_com_varias_bases(b)
            _remover_campo_ausente_explicado(b)
            b.explicacao = gerar_explicacao_bloco(b, vigencia_campanha=vigencia)
            b.codigoPython = gerar_codigo_regra(b)
        return blocos


# ---------------------------------------------------------------------- IA-6
def _herdar_do_bloco_atual(b: BlocoInterno, atual: BlocoProposta) -> None:
    """
    Reinterpretação localizada: o texto alterado substitui só o que cita.

    Público, faixa e remuneração não mencionados no texto novo vêm do bloco atual; o que o texto
    cita é sempre reinterpretado (inclusive para trocar um valor editado manualmente, cabendo ao
    frontend confirmar a substituição).
    """
    raw, bl = b.raw, b.bloco
    if not any((raw.marca_raw, raw.cargo_raw, raw.loja_raw, raw.canal, raw.matricula_raw)):
        ca = atual.condicoes
        bl.condicoes.canal = ca.canal
        bl.condicoes.codMarca, bl.condicoes.descrMarca = ca.codMarca, ca.descrMarca
        bl.condicoes.codCargo, bl.condicoes.descriCargo = ca.codCargo, ca.descriCargo
        bl.condicoes.codLoja = ca.codLoja
        bl.condicoes.matricula = ca.matricula
    if not (raw.faixa_min_raw or raw.faixa_max_raw) and bl.condicoes.faixaValor is None:
        bl.condicoes.faixaValor = atual.condicoes.faixaValor.model_copy() if atual.condicoes.faixaValor else None
    if not any((raw.taxa_raw, raw.operacao_raw, raw.bonus_percentual_raw, raw.bonus_valor_raw)):
        bl.bonus = atual.bonus.model_copy() if atual.bonus else None
        op = atual.operacao
        if op is not None and op.tipo != "TAXA_ABSOLUTA":
            # herda o AJUSTE, não a taxa final: ela é recalculada com a base do público atual
            raw.operacao_raw = _texto_da_operacao(op.tipo, op.valor)
            bl.pendencias = [p for p in bl.pendencias if p.campo != "taxa"]
            bl.pendencias.append(
                pendencia(
                    CodigoPendencia.CAMPO_AUSENTE,
                    f"Ajuste herdado da regra ({descrever_operacao(op.tipo, op.valor)}) depende da comissão base "
                    "do público atual; a taxa final ainda não foi calculada.",
                    "taxa",
                    "Confirme o público para consultar a base de comissão.",
                )
            )
            return
        bl.taxa = atual.taxa
        bl.operacao = op.model_copy() if op else None
        if bl.taxa is not None or bl.bonus is not None:
            bl.pendencias = [p for p in bl.pendencias if p.campo != "taxa"]


def _texto_da_operacao(tipo: str, valor: Decimal) -> str:
    """Expressão canônica que `interpretar_operacao` reconhece de volta como o mesmo ajuste."""
    pct = format((valor * 100).normalize(), "f")
    return {
        "ADICIONAR_PP": f"mais {pct} pontos percentuais",
        "REDUZIR_PP": f"menos {pct} pontos percentuais",
        "AUMENTAR_PERCENTUAL": f"aumentar {pct}%",
        "REDUZIR_PERCENTUAL": f"reduzir {pct}%",
    }[tipo]


# ---------------------------------------------------------------------- IA-5
def _normalizar_operacao_do_bloco(b: BlocoInterno) -> None:
    raw, bl = b.raw, b.bloco
    if not (raw.operacao_raw and raw.operacao_raw.strip()):
        return
    r = interpretar_operacao(raw.operacao_raw)
    if r.tipo == "TAXA_ABSOLUTA" and r.valor is not None:
        # o LLM marcou como ajuste, mas o texto traz um valor absoluto ('3%'): a taxa é o próprio valor
        bl.operacao = Operacao(tipo="TAXA_ABSOLUTA", valor=r.valor)
        bl.taxa = r.valor
        bl.pendencias = [
            p for p in bl.pendencias if not (p.codigo == CodigoPendencia.CAMPO_AUSENTE and p.campo == "taxa")
        ]
        return
    if r.tipo and r.valor is not None:
        bl.operacao = Operacao(tipo=r.tipo, valor=r.valor)
    for msg in r.pendencias:
        bl.pendencias.append(
            pendencia(
                CodigoPendencia.TAXA_INVALIDA,
                msg,
                "taxa",
                "Qual ajuste deve ser aplicado sobre a base?" if r.ambigua else None,
            )
        )


def _remover_campo_ausente_explicado(bl: BlocoProposta) -> None:
    """Sem taxa por base ausente, ambiguidade ou resultado inválido: a pendência específica basta."""
    especificas = (CodigoPendencia.BASE_AUSENTE, CodigoPendencia.TAXA_INVALIDA, CodigoPendencia.AMBIGUIDADE_PUBLICO)
    if any(p.campo == "taxa" and p.codigo in especificas for p in bl.pendencias):
        bl.pendencias = [
            p for p in bl.pendencias if not (p.codigo == CodigoPendencia.CAMPO_AUSENTE and p.campo == "taxa")
        ]


def _sinalizar_publico_com_varias_bases(bl: BlocoProposta) -> None:
    """
    Ajuste pendente porque o público não fixa marca e cargo: cada combinação tem sua base, então
    não há uma taxa única. Pede a restrição do público (ou a divisão da regra) em vez de escolher.
    """
    if not bl.operacao or bl.operacao.tipo == "TAXA_ABSOLUTA" or bl.taxa is not None:
        return
    faltam = []
    for campo, valor, nome in (
        ("condicoes.codMarca", bl.condicoes.codMarca, "marca"),
        ("condicoes.codCargo", bl.condicoes.codCargo, "cargo"),
    ):
        # termo citado e não resolvido já tem pendência própria (ambiguidade/cadastro inexistente)
        if valor is None and not any(p.campo == campo for p in bl.pendencias):
            faltam.append(nome)
    if not faltam:
        return
    bl.pendencias = [p for p in bl.pendencias if not (p.codigo == CodigoPendencia.CAMPO_AUSENTE and p.campo == "taxa")]
    bl.pendencias.append(
        pendencia(
            CodigoPendencia.AMBIGUIDADE_PUBLICO,
            f"O ajuste ({descrever_operacao(bl.operacao.tipo, bl.operacao.valor)}) depende da base de comissão, "
            f"que varia por marca e cargo, mas a regra não define {' nem '.join(faltam)}; "
            "o público pode abranger várias bases.",
            "taxa",
            f"Restrinja o público informando {' e '.join(faltam)}, divida a regra por base "
            "ou informe a taxa final desejada.",
        )
    )
