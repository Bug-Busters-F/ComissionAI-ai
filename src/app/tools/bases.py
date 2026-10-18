"""Ferramenta de consulta da base de comissão (marca + cargo + competência)."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, Field

from app.schemas.proposta import ReferenciaBase
from app.tools.base import Tool, ToolResult
from app.tools.client import BackendClient, BackendErro


class ConsultarBaseArgs(BaseModel):
    codMarca: int
    codCargo: int
    competencia: str = Field(pattern=r"^\d{4}-\d{2}$")


class ConsultarBaseComissao(Tool):
    nome = "consultar_base_comissao"
    descricao = (
        "Consulta a taxa base de comissão por marca, cargo e competência (YYYY-MM). "
        "SEM_DADOS quando não há base cadastrada; nunca estima a taxa."
    )
    schema_entrada = ConsultarBaseArgs

    def __init__(self, client: BackendClient) -> None:
        self._client = client

    def executar(self, args: ConsultarBaseArgs) -> ToolResult:  # type: ignore[override]
        try:
            corpo = self._client.get(
                "/bases",
                {"codMarca": args.codMarca, "codCargo": args.codCargo, "competencia": args.competencia},
            )
        except BackendErro as exc:
            return ToolResult.falha(exc.tipo, exc.detalhe, exc.tentativas)
        if "encontrado" not in corpo:
            return ToolResult.falha("RESPOSTA_INVALIDA", "campo 'encontrado' ausente")
        if not corpo["encontrado"]:
            return ToolResult.sem_dados()
        try:
            taxa = Decimal(str(corpo["taxa"]))
        except (KeyError, InvalidOperation):
            return ToolResult.falha("RESPOSTA_INVALIDA", "taxa ausente ou inválida")
        ref = ReferenciaBase(
            fonte="BASE_COMISS",
            chave={
                "codMarca": args.codMarca,
                "codCargo": args.codCargo,
                "competencia": corpo.get("competenciaUsada", args.competencia),
            },
            taxaBase=taxa,
            consultadaEm=datetime.now(timezone.utc),
        )
        return ToolResult(status="OK", dados={**corpo, "taxa": str(taxa)}, referencias=[ref])
