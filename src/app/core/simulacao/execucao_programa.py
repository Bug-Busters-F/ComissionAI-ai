"""
Execução do programa aprovado no backend (IA-10 / BUG-123; produtor do código: BACK-9; consumidores: BACK-11
na simulação e a apuração definitiva).

O backend gera e aprova `calcular_comissao(venda)` com as regras embutidas e consolida os cenários em Java;
a IA só executa o programa no sandbox, item a item, e devolve a comissão de cada item. Fail-closed:
código rejeitado, erro em qualquer item, limite de tempo/memória ou retorno inválido -> nenhum resultado
parcial (o backend não tem fallback para Java).
"""

from __future__ import annotations

import hashlib
import logging
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.core.config import settings
from app.core.erros import corpo_erro
from app.core.simulacao.sandbox import Sandbox
from app.core.simulacao.validador import validar_programa
from app.schemas.execucao import ExecutarProgramaRequest, ExecutarProgramaResponse, ResultadoItem

logger = logging.getLogger(__name__)

CENT = Decimal("0.01")


class VolumeExcedido(ValueError):
    pass


class FalhaExecucao(Exception):
    """Falha atribuível ao programa ou aos dados: vira 422 com o corpo do contrato do backend."""

    def __init__(self, error_code: str, erro: str, detalhe: str, violacoes: list[str],
                 resposta: ExecutarProgramaResponse) -> None:
        super().__init__(detalhe)
        self.error_code = error_code  # PROGRAMA_REJEITADO | PROGRAMA_FALHOU
        self.erro = erro
        self.detalhe = detalhe
        self.violacoes = violacoes
        self.resposta = resposta

    def corpo(self) -> dict:
        base = self.resposta.model_dump(mode="json")
        return {**base, **corpo_erro(self.error_code, self.detalhe)}


def assinatura(codigo: str) -> str:
    """Mesmo cálculo de `CampanhaProgramaPython.calcularChecksum` (sha256 hex do UTF-8)."""
    return hashlib.sha256(codigo.encode("utf-8")).hexdigest()


def executar(request: ExecutarProgramaRequest, sandbox: Sandbox | None = None) -> ExecutarProgramaResponse:
    if len(request.itens) > settings.exec_max_itens:
        raise VolumeExcedido(f"O lote tem {len(request.itens)} itens; o limite da execução é "
                             f"{settings.exec_max_itens}.")
    codigo = request.codigoFonte
    base = {"assinaturaPrograma": assinatura(codigo), "contexto": request.contexto,
            "totalItens": len(request.itens)}

    def falha(error_code: str, erro: str, detalhe: str, violacoes: list[str] | None = None) -> FalhaExecucao:
        resp = ExecutarProgramaResponse(sucesso=False, erro=erro, detalhe=detalhe, violacoes=violacoes or [], **base)
        logger.warning("executar-programa falhou: %s %s (%d itens)", error_code, erro, len(request.itens))
        return FalhaExecucao(error_code, erro, detalhe, violacoes or [], resp)

    validacao = validar_programa(codigo, settings.exec_max_code_lines, settings.exec_max_code_bytes)
    if not validacao.ok:
        raise falha("PROGRAMA_REJEITADO", "VALIDACAO", validacao.violacoes[0], validacao.violacoes)
    if not request.itens:
        return ExecutarProgramaResponse(sucesso=True, resultados=[], **base)

    itens = [{"id": i.id, "venda": i.venda, "contexto": i.contexto} for i in request.itens]
    res = (sandbox or Sandbox()).executar_programa(codigo, validacao.aridade, itens)
    if not res.ok:
        raise falha("PROGRAMA_FALHOU", res.erro or "ERRO_CODIGO", res.detalhe, res.violacoes)

    resultados: list[ResultadoItem] = []
    for item, bruto in zip(request.itens, res.resultados):
        if bruto is None:
            resultados.append(ResultadoItem(id=item.id, aplicada=False, comissao=None))
            continue
        try:
            valor = Decimal(str(bruto)).quantize(CENT, rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError):
            raise falha("PROGRAMA_FALHOU", "SAIDA_INVALIDA", f"item {item.id}: comissão não numérica.") from None
        if valor < 0:
            raise falha("PROGRAMA_FALHOU", "SAIDA_INVALIDA", f"item {item.id}: comissão negativa ({valor}).")
        resultados.append(ResultadoItem(id=item.id, aplicada=True, comissao=valor))
    return ExecutarProgramaResponse(sucesso=True, resultados=resultados, **base)
