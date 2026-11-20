"""
Exporta o JSON Schema dos contratos da Sprint 3 (IA-10) para docs/contratos/.

    python scripts/exportar_contratos.py

`tests/test_contrato_sprint3.py` falha se os arquivos estiverem desatualizados em relação aos modelos
Pydantic: qualquer mudança de contrato precisa ser exportada (e revisada) junto com o código.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from app.schemas.anomalia import AnalisarAnomaliasRequest, AnalisarAnomaliasResponse  # noqa: E402
from app.schemas.execucao import (  # noqa: E402
    ExecutarProgramaErro,
    ExecutarProgramaRequest,
    ExecutarProgramaResponse,
)
from app.schemas.proposta import (  # noqa: E402
    GerarProgramaRequest,
    ProgramaGeradoResponse,
    SimularRequest,
    SimularResponse,
)

DESTINO = RAIZ / "docs" / "contratos"
MODELOS = {
    "gerar-programa.request": (GerarProgramaRequest, "validation"),
    "gerar-programa.response": (ProgramaGeradoResponse, "serialization"),
    "simular.request": (SimularRequest, "validation"),
    "simular.response": (SimularResponse, "serialization"),
    "anomalias-analisar.request": (AnalisarAnomaliasRequest, "validation"),
    "anomalias-analisar.response": (AnalisarAnomaliasResponse, "serialization"),
    "executar-programa.request": (ExecutarProgramaRequest, "validation"),
    "executar-programa.response": (ExecutarProgramaResponse, "serialization"),
    "executar-programa.erro": (ExecutarProgramaErro, "serialization"),
}


def schemas() -> dict[str, str]:
    return {f"{nome}.schema.json": json.dumps(modelo.model_json_schema(mode=modo), ensure_ascii=False, indent=2,
                                              sort_keys=True) + "\n"
            for nome, (modelo, modo) in MODELOS.items()}


def main() -> None:
    DESTINO.mkdir(parents=True, exist_ok=True)
    for nome, conteudo in schemas().items():
        (DESTINO / nome).write_text(conteudo, encoding="utf-8", newline="\n")
        print(f"docs/contratos/{nome}")


if __name__ == "__main__":
    main()
