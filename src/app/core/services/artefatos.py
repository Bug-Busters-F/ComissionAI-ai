"""
Serviço de atualização de artefatos após edição manual (IA-6 / BUG-57).

Atualiza explicação e código Python a partir dos campos atuais da proposta,
preservando escolhas manuais do usuário sem reinterpretar o texto.
"""

from app.core.pendencias import pendencia
from app.core.prompts.codigo_regra_prompt import gerar_codigo_regra
from app.core.prompts.explicacao_prompt import gerar_explicacao_bloco
from app.schemas.proposta import (
    AtualizarArtefatosRequest,
    AtualizarArtefatosResponse,
    BlocoProposta,
    CodigoPendencia,
    Operacao,
)


class ServicoArtefatos:
    """Gerencia a atualização de artefatos (explicações e código) após alterações."""

    def atualizar(self, request: AtualizarArtefatosRequest) -> AtualizarArtefatosResponse:
        """
        Gera nova explicação e código Python para o bloco com base nos campos atuais.

        Campos listados em `camposEditados` são tratados como MANUAL, salvo quando `origemCampos`
        disser o contrário. Nenhum campo é reinterpretado ou substituído.
        """
        bloco = request.bloco.model_copy(deep=True)
        origens: dict[str, str] = {campo: "MANUAL" for campo in request.camposEditados}
        origens.update(request.origemCampos)

        if origens.get("taxa") == "MANUAL":
            _aplicar_taxa_manual(bloco)

        bloco.explicacao = gerar_explicacao_bloco(bloco, origens)
        bloco.codigoPython = gerar_codigo_regra(bloco)
        return AtualizarArtefatosResponse(contexto=request.contexto, bloco=bloco)


def _aplicar_taxa_manual(bloco: BlocoProposta) -> None:
    """
    Taxa digitada pelo gestor passa a ser a origem da regra: a operação vira TAXA_ABSOLUTA com o
    novo valor, a referência à base deixa de valer e as pendências sobre a taxa são substituídas.
    """
    bloco.pendencias = [p for p in bloco.pendencias if p.campo != "taxa"]
    bloco.referencias = [r for r in bloco.referencias if r.fonte != "BASE_COMISS"]
    if bloco.taxa is not None:
        bloco.operacao = Operacao(tipo="TAXA_ABSOLUTA", valor=bloco.taxa)
        return
    bloco.operacao = None
    if bloco.bonus is None:
        bloco.pendencias.append(
            pendencia(
                CodigoPendencia.CAMPO_AUSENTE,
                "A taxa foi removida na edição manual.",
                "taxa",
                "Qual é o percentual de comissão desta regra?",
            )
        )
