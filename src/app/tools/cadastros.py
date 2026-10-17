"""Ferramentas de cadastro: resolver público (marca/loja/cargo) e validar matrícula."""

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.schemas.proposta import ReferenciaBase
from app.tools.base import Tool, ToolResult
from app.tools.client import BackendClient, BackendErro


def _norm(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    sem = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem.strip().upper())


class ResolverPublicoArgs(BaseModel):
    marca: str | None = Field(default=None, description="Nome ou código da marca.")
    loja: str | None = Field(default=None, description="Nome ou código da loja.")
    cargo: str | None = Field(default=None, description="Nome ou código do cargo.")

    @model_validator(mode="after")
    def _algum(self) -> "ResolverPublicoArgs":
        if not (self.marca or self.loja or self.cargo):
            raise ValueError("Informe ao menos marca, loja ou cargo.")
        return self


_PRECEDENCIA = {"FALHA": 4, "AMBIGUO": 3, "SEM_DADOS": 2, "OK": 1}


class ResolverPublico(Tool):
    nome = "resolver_publico"
    descricao = (
        "Resolve nomes ou códigos de marca, loja e cargo contra os cadastros reais. "
        "Retorna AMBIGUO com candidatos quando houver mais de uma possibilidade (nunca escolhe)."
    )
    schema_entrada = ResolverPublicoArgs

    def __init__(self, client: BackendClient) -> None:
        self._client = client

    def executar(self, args: ResolverPublicoArgs) -> ToolResult:  # type: ignore[override]
        dimensoes: dict[str, dict[str, Any]] = {}
        referencias: list[ReferenciaBase] = []
        tentativas = 1
        for dim, rota, termo in (
            ("marca", "/marcas", args.marca),
            ("loja", "/lojas", args.loja),
            ("cargo", "/cargos", args.cargo),
        ):
            if not termo:
                continue
            resultado, refs = self._resolver(dim, rota, termo)
            dimensoes[dim] = resultado
            referencias += refs
        status = max((d["status"] for d in dimensoes.values()), key=_PRECEDENCIA.__getitem__)
        erros = [d for d in dimensoes.values() if d["status"] == "FALHA"]
        if status == "FALHA" and len(erros) == len(dimensoes):
            e = erros[0]["erro"]
            return ToolResult.falha(e["tipo"], e["detalhe"])
        return ToolResult(status=status, dados={"dimensoes": dimensoes}, referencias=referencias,
                          tentativas=tentativas)

    def _resolver(self, dim: str, rota: str, termo: str) -> tuple[dict[str, Any], list[ReferenciaBase]]:
        termo = termo.strip()
        params = {"codigo": int(termo)} if termo.isdigit() else {"nome": termo}
        try:
            corpo = self._client.get(rota, params)
        except BackendErro as exc:
            return {"status": "FALHA", "erro": {"tipo": exc.tipo, "detalhe": exc.detalhe}}, []
        itens = corpo.get("itens")
        if not isinstance(itens, list) or "encontrado" not in corpo:
            return {"status": "FALHA", "erro": {"tipo": "RESPOSTA_INVALIDA", "detalhe": rota}}, []
        if not corpo["encontrado"] or not itens:
            return {"status": "SEM_DADOS", "termo": termo}, []
        escolhidos = itens
        if len(itens) > 1 and not termo.isdigit():
            exatos = [i for i in itens if _norm(str(i.get("descricao", ""))) == _norm(termo)]
            if len(exatos) == 1:
                escolhidos = exatos
        if len(escolhidos) > 1:
            return {"status": "AMBIGUO", "termo": termo, "candidatos": escolhidos}, []
        item = escolhidos[0]
        ref = ReferenciaBase(
            fonte="CADASTRO",
            chave={dim: item.get("codigo")},
            consultadaEm=datetime.now(timezone.utc),
        )
        return {"status": "OK", "termo": termo, "resolvido": item}, [ref]


class ValidarMatriculaArgs(BaseModel):
    matricula: str = Field(min_length=1)


class ValidarMatricula(Tool):
    nome = "validar_matricula"
    descricao = (
        "Valida se uma matrícula existe e devolve loja, cargo, marca e datas de admissão/demissão."
    )
    schema_entrada = ValidarMatriculaArgs

    def __init__(self, client: BackendClient) -> None:
        self._client = client

    def executar(self, args: ValidarMatriculaArgs) -> ToolResult:  # type: ignore[override]
        matricula = args.matricula.strip()
        try:
            corpo = self._client.get(f"/matriculas/{matricula}")
        except BackendErro as exc:
            return ToolResult.falha(exc.tipo, exc.detalhe, exc.tentativas)
        if "encontrado" not in corpo:
            return ToolResult.falha("RESPOSTA_INVALIDA", "campo 'encontrado' ausente")
        if not corpo["encontrado"]:
            return ToolResult.sem_dados()
        ref = ReferenciaBase(
            fonte="CADASTRO", chave={"matricula": matricula}, consultadaEm=datetime.now(timezone.utc)
        )
        return ToolResult(status="OK", dados=corpo, referencias=[ref])
