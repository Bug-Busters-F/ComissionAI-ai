"""
Persistência em arquivo do código gerado por /gerar-programa (IA-2), pra permitir revisão
posterior por assinatura. O serviço de IA não tem banco; o backend (Java) guarda só a
assinatura como referência e consulta GET /api/v2/programa/{assinatura} quando precisar do
código de volta. TEMPLATE não é persistido (é fixo, sempre recuperável via templates.py).
"""

import json
from pathlib import Path

from app.core.config import settings


def _arquivo(assinatura: str) -> Path:
    if not assinatura or any(c not in "0123456789abcdef" for c in assinatura.lower()):
        raise ValueError("Assinatura inválida.")
    return Path(settings.sim_dir_programas) / f"{assinatura}.json"


def salvar(assinatura: str, codigo: str, premissas: list[str]) -> None:
    caminho = _arquivo(assinatura)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps({"assinatura": assinatura, "codigo": codigo, "premissas": premissas}, ensure_ascii=False),
        encoding="utf-8",
    )


def buscar(assinatura: str) -> dict | None:
    try:
        caminho = _arquivo(assinatura)
    except ValueError:
        return None
    if not caminho.is_file():
        return None
    return json.loads(caminho.read_text(encoding="utf-8"))
