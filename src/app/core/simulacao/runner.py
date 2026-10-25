"""
Processo filho do sandbox. Executado como `python -I runner.py`
com ambiente vazio. Lê um JSON em stdin e escreve UM JSON em stdout.

Camadas aqui: limites de recurso (rlimit), builtins restritos, `__import__` por lista de
permissão (módulos pré-carregados) e audit hook que MATA o processo na primeira violação
(o código gerado não consegue capturar a violação).

Este arquivo só usa a biblioteca padrão e não importa nada do pacote `app`.
"""

import json
import os
try:
    import resource
except ImportError:  # Windows (só desenvolvimento): sem rlimit; produção roda em Linux (Docker) com limites
    resource = None
import sys

ALLOWED = ("decimal", "datetime", "math", "statistics", "collections", "itertools", "functools",
           "typing", "dataclasses", "enum")
for _m in ALLOWED:
    __import__(_m)
import builtins as _b  # noqa: E402  (pré-carregado)
from decimal import Decimal  # noqa: E402

SAFE_NAMES = (
    "abs all any bool dict enumerate filter float int len list map max min range reversed round set sorted "
    "str sum tuple zip isinstance divmod pow iter next True False None Exception ValueError ZeroDivisionError "
    "ArithmeticError KeyError IndexError TypeError"
).split()

_EXIT = os._exit
_PREFIXOS_PROIBIDOS = (
    "socket.", "subprocess.", "ctypes.", "os.system", "os.exec", "os.spawn", "os.posix_spawn", "os.fork",
    "os.forkpty", "os.kill", "os.remove", "os.rename", "os.mkdir", "os.rmdir", "os.chmod", "os.chown",
    "os.link", "os.symlink", "os.truncate", "os.putenv", "os.unsetenv", "os.chdir", "os.listdir", "os.scandir",
    "shutil.", "pickle.", "marshal.", "sys.settrace", "sys.setprofile", "urllib.", "http.", "ftplib.", "smtplib.",
    "webbrowser.", "pty.", "signal.", "fcntl.", "mmap.", "sqlite3.", "glob.", "tempfile.", "open", "import",
)


def _hook(evento, args):
    if evento in ("exec", "compile"):
        return
    for p in _PREFIXOS_PROIBIDOS:
        if evento == p or evento.startswith(p):
            _EXIT(97)


def _imp(nome, globals=None, locals=None, fromlist=(), level=0):
    raiz = nome.split(".")[0]
    if level or raiz not in ALLOWED:
        raise ImportError("import não permitido")
    return __import__(nome, globals, locals, fromlist, level)


def _converter(obj):
    if isinstance(obj, dict):
        return {str(k): _converter(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_converter(v) for v in obj]
    if isinstance(obj, Decimal):
        if not obj.is_finite():
            raise ValueError("valor não finito")
        return str(obj)
    if isinstance(obj, float):
        if obj != obj or obj in (float("inf"), float("-inf")):
            raise ValueError("valor não finito")
        return obj
    if isinstance(obj, (str, int, bool)) or obj is None:
        return obj
    raise TypeError("tipo não serializável: " + type(obj).__name__)


def _numerico(obj, campos):
    """Converte campos monetários/percentuais (str) em Decimal, em dicts aninhados."""
    if isinstance(obj, dict):
        return {k: (Decimal(str(v)) if k in campos and v is not None else _numerico(v, campos)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_numerico(v, campos) for v in obj]
    return obj


def main():
    carga = json.loads(sys.stdin.read())
    cfg = carga["limites"]
    if resource is not None:
        mem = int(cfg["memoria_mb"]) * 1024 * 1024
        cpu = int(cfg["cpu_s"])
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    campos = {"valorVenda", "taxa", "min", "max", "percentual", "valorFixo", "multiplicadorVendas"}
    vendas = _numerico(carga["vendas"], campos)
    regras = _numerico(carga["regras"], campos)
    cenarios = _numerico(carga["cenarios"], campos)

    seguros = {n: getattr(_b, n) for n in SAFE_NAMES}
    seguros["__import__"] = _imp
    ambiente = {"__builtins__": seguros, "__name__": "sandbox"}

    codigo = compile(carga["codigo"], "<simulacao>", "exec")
    sys.addaudithook(_hook)
    exec(codigo, ambiente)
    simular = ambiente["simular"]
    saida = [_converter(simular(vendas, regras, c)) for c in cenarios]
    texto = json.dumps({"resultados": saida})
    if len(texto) > int(cfg["saida_max_bytes"]):
        _EXIT(98)
    sys.stdout.write(texto)
    sys.stdout.flush()


if __name__ == "__main__":
    try:
        main()
    except MemoryError:
        _EXIT(99)
    except Exception as exc:  # erro do código do usuário: reporta tipo e mensagem curta
        sys.stdout.write(json.dumps({"erro": type(exc).__name__ + ": " + str(exc)[:200]}))
        sys.stdout.flush()
        _EXIT(2)
