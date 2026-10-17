"""
Executor isolado de código gerado.

Subprocesso endurecido dentro do container do serviço: `python -I`, ambiente vazio,
diretório temporário próprio, rlimits, builtins restritos, audit hook e timeout duro com kill.
Interface estável (`Sandbox.executar`) para trocar por container sem retrabalho.
"""

import json
import logging
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.simulacao.validador import validar_codigo

logger = logging.getLogger(__name__)

_RUNNER = Path(__file__).with_name("runner.py")


@dataclass
class ResultadoSandbox:
    ok: bool
    resultados: list[dict[str, Any]] = field(default_factory=list)
    erro: str | None = None  # VALIDACAO | TIMEOUT | VIOLACAO | MEMORIA | SAIDA_EXCESSIVA | ERRO_CODIGO | SAIDA_INVALIDA
    detalhe: str = ""
    violacoes: list[str] = field(default_factory=list)


class Sandbox:
    def __init__(self) -> None:
        pass

    def executar(
        self,
        codigo: str,
        vendas: list[dict[str, Any]],
        regras: list[dict[str, Any]],
        cenarios: list[dict[str, Any]],
    ) -> ResultadoSandbox:
        validacao = validar_codigo(codigo, settings.sim_max_code_lines, settings.sim_max_code_bytes)
        if not validacao.ok:
            logger.warning("Código rejeitado pela análise estática: %d violação(ões)", len(validacao.violacoes))
            return ResultadoSandbox(False, erro="VALIDACAO", detalhe=validacao.violacoes[0], violacoes=validacao.violacoes)
        if len(vendas) > settings.sim_max_registros:
            return ResultadoSandbox(False, erro="VALIDACAO", detalhe="Registros acima do limite da simulação.")

        carga = json.dumps(
            {
                "codigo": codigo,
                "vendas": vendas,
                "regras": regras,
                "cenarios": cenarios,
                "limites": {
                    "memoria_mb": settings.sim_max_memory_mb,
                    "cpu_s": int(settings.sim_max_seconds) + 1,
                    "saida_max_bytes": settings.sim_max_output_kb * 1024,
                },
            },
            default=str,
        )
        with tempfile.TemporaryDirectory(prefix="sim_") as tmp:
            try:
                proc = subprocess.run(
                    [sys.executable, "-I", str(_RUNNER)],
                    input=carga.encode("utf-8"),
                    capture_output=True,
                    timeout=settings.sim_max_seconds,
                    cwd=tmp,
                    env={},
                    close_fds=True,
                )
            except subprocess.TimeoutExpired:
                return ResultadoSandbox(False, erro="TIMEOUT", detalhe=f"Excedeu {settings.sim_max_seconds:g}s.")
        saida = proc.stdout
        if proc.returncode == 97:
            return ResultadoSandbox(False, erro="VIOLACAO", detalhe="Operação proibida bloqueada pelo sandbox.")
        if proc.returncode == 99 or (proc.returncode < 0 and -proc.returncode in (9, 11)):
            return ResultadoSandbox(False, erro="MEMORIA", detalhe="Memória ou CPU acima do limite.")
        if proc.returncode == 98:
            return ResultadoSandbox(False, erro="SAIDA_EXCESSIVA", detalhe="Saída acima do limite.")
        if proc.returncode < 0:  # SIGXCPU etc.
            return ResultadoSandbox(False, erro="TIMEOUT", detalhe="CPU acima do limite.")
        try:
            corpo = json.loads(saida.decode("utf-8")) if saida else {}
        except ValueError:
            return ResultadoSandbox(False, erro="SAIDA_INVALIDA", detalhe="Saída não é JSON.")
        if "erro" in corpo:
            return ResultadoSandbox(False, erro="ERRO_CODIGO", detalhe=str(corpo["erro"]))
        if proc.returncode != 0 or not isinstance(corpo.get("resultados"), list):
            return ResultadoSandbox(False, erro="SAIDA_INVALIDA", detalhe=f"código de saída {proc.returncode}")
        return ResultadoSandbox(True, resultados=corpo["resultados"])
