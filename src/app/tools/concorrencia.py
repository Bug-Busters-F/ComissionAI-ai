"""Ferramenta de consulta de regras ativas concorrentes."""

from datetime import date, datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.proposta import ReferenciaBase
from app.tools.base import Tool, ToolResult
from app.tools.client import BackendClient, BackendErro


class CondicoesConsulta(BaseModel):
    canal: str | None = None
    codMarca: int | None = None
    codLoja: int | None = None
    codCargo: int | None = None
    matricula: str | None = None


class ConsultarConcorrenciaArgs(BaseModel):
    condicoes: CondicoesConsulta = Field(default_factory=CondicoesConsulta)
    dataInicio: date | None = None
    dataFim: date | None = None
    ignorarCampanhaId: str | None = Field(
        default=None,
        description="Na edição de campanha versionada, a versão anterior não conta como conflito.",
    )


class ConsultarRegrasConcorrentes(Tool):
    nome = "consultar_regras_concorrentes"
    descricao = (
        "Lista regras ativas que colidem com as condições e a vigência informadas, "
        "com a especificidade de cada uma. SEM_DADOS quando não há conflito."
    )
    schema_entrada = ConsultarConcorrenciaArgs

    def __init__(self, client: BackendClient) -> None:
        self._client = client

    def executar(self, args: ConsultarConcorrenciaArgs) -> ToolResult:  # type: ignore[override]
        corpo_req: dict[str, Any] = {
            "condicoes": args.condicoes.model_dump(exclude_none=True),
            "dataInicio": args.dataInicio.isoformat() if args.dataInicio else None,
            "dataFim": args.dataFim.isoformat() if args.dataFim else None,
            "ignorarCampanhaId": args.ignorarCampanhaId,
        }
        try:
            corpo = self._client.post("/regras-concorrentes", corpo_req)
        except BackendErro as exc:
            return ToolResult.falha(exc.tipo, exc.detalhe, exc.tentativas)
        conflitos = corpo.get("conflitos")
        if not isinstance(conflitos, list):
            return ToolResult.falha("RESPOSTA_INVALIDA", "campo 'conflitos' ausente")
        if not conflitos:
            return ToolResult.sem_dados()
        agora = datetime.now(timezone.utc)
        refs = [
            ReferenciaBase(fonte="TB_REGRA", chave={"idRegra": c.get("idRegra")}, consultadaEm=agora)
            for c in conflitos
        ]
        return ToolResult(status="OK", dados={"conflitos": conflitos}, referencias=refs)
