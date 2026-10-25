"""Estado de uma execução do agente: blocos, lacunas, trilha, cache e contadores."""

import json
from dataclasses import dataclass, field
from typing import Any

from app.core.services.campanha import BlocoInterno
from app.schemas.proposta import EvidenciaTool
from app.tools.base import ToolResult


@dataclass(frozen=True)
class Lacuna:
    """Informação faltante que uma ferramenta pode resolver."""

    id: str  # ex.: "PUBLICO:p1"
    tipo: str  # PUBLICO | MATRICULA | BASE | CONCORRENCIA
    bloco: str  # idLocal
    ferramenta: str
    argumentos: dict[str, Any]


@dataclass
class EstadoAgente:
    blocos: list[BlocoInterno]
    competencia: str | None = None
    ignorar_campanha_id: str | None = None
    trilha: list[EvidenciaTool] = field(default_factory=list)
    tratadas: set[str] = field(default_factory=set)
    cache: dict[str, ToolResult] = field(default_factory=dict)

    def bloco(self, id_local: str) -> BlocoInterno:
        return next(b for b in self.blocos if b.bloco.idLocal == id_local)

    @staticmethod
    def chave_cache(ferramenta: str, argumentos: dict[str, Any]) -> str:
        return ferramenta + ":" + json.dumps(argumentos, sort_keys=True, default=str, ensure_ascii=False)

    def competencia_do_bloco(self, b: BlocoInterno) -> str | None:
        if self.competencia:
            return self.competencia
        if b.bloco.dataInicio:
            return b.bloco.dataInicio.strftime("%Y-%m")
        return None

    def lacunas_abertas(self) -> list[Lacuna]:
        """Calculadas de forma determinística a partir do estado (o agente não 'esquece' lacunas)."""
        abertas: list[Lacuna] = []
        for b in self.blocos:
            bl, raw = b.bloco, b.raw
            id_ = bl.idLocal
            # 1) público: termo citado e código ainda não resolvido
            if b.lacunas_cadastro and f"PUBLICO:{id_}" not in self.tratadas:
                args = {
                    d: getattr(raw, f"{d}_raw")
                    for d in sorted(b.lacunas_cadastro)
                    if getattr(raw, f"{d}_raw")
                }
                if args:
                    abertas.append(Lacuna(f"PUBLICO:{id_}", "PUBLICO", id_, "resolver_publico", args))
            # 2) matrícula citada
            if bl.condicoes.matricula and f"MATRICULA:{id_}" not in self.tratadas:
                abertas.append(
                    Lacuna(f"MATRICULA:{id_}", "MATRICULA", id_, "validar_matricula",
                           {"matricula": bl.condicoes.matricula})
                )
            # 3) base: ajuste sobre a comissão base (IA-5) com marca e cargo resolvidos
            competencia = self.competencia_do_bloco(b)
            if (
                raw.operacao_raw
                and bl.condicoes.codMarca is not None
                and bl.condicoes.codCargo is not None
                and competencia
                and f"BASE:{id_}" not in self.tratadas
            ):
                abertas.append(
                    Lacuna(f"BASE:{id_}", "BASE", id_, "consultar_base_comissao",
                           {"codMarca": bl.condicoes.codMarca, "codCargo": bl.condicoes.codCargo,
                            "competencia": competencia})
                )
            # 4) concorrência: só depois do público resolvido/tentado e com vigência e remuneração
            publico_pendente = f"PUBLICO:{id_}" in {l.id for l in abertas}
            tem_publico = any(
                v is not None
                for v in (bl.condicoes.codMarca, bl.condicoes.codCargo, bl.condicoes.codLoja,
                          bl.condicoes.matricula, bl.condicoes.canal)
            )
            if (
                not publico_pendente
                and tem_publico
                and (bl.taxa is not None or bl.bonus is not None)
                and bl.dataInicio
                and f"CONCORRENCIA:{id_}" not in self.tratadas
            ):
                abertas.append(
                    Lacuna(
                        f"CONCORRENCIA:{id_}", "CONCORRENCIA", id_, "consultar_regras_concorrentes",
                        {
                            "condicoes": {
                                k: v
                                for k, v in {
                                    "canal": bl.condicoes.canal,
                                    "codMarca": bl.condicoes.codMarca,
                                    "codLoja": bl.condicoes.codLoja,
                                    "codCargo": bl.condicoes.codCargo,
                                    "matricula": bl.condicoes.matricula,
                                }.items()
                                if v is not None
                            },
                            "dataInicio": bl.dataInicio.isoformat(),
                            "dataFim": bl.dataFim.isoformat() if bl.dataFim else None,
                            "ignorarCampanhaId": self.ignorar_campanha_id,
                        },
                    )
                )
        return abertas
