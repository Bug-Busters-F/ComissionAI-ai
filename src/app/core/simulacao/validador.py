"""
Análise estática (AST) do código gerado, por LISTA DE PERMISSÃO.

Rejeita antes de executar. A análise é a primeira camada; o sandbox (runner) é a segunda.
"""

import ast
import builtins
from dataclasses import dataclass, field

IMPORTS_PERMITIDOS = frozenset(
    {"decimal", "datetime", "math", "statistics", "collections", "itertools", "functools", "typing",
     "dataclasses", "enum"}
)

BUILTINS_PERMITIDOS = frozenset(
    {"abs", "all", "any", "bool", "dict", "enumerate", "filter", "float", "int", "len", "list", "map",
     "max", "min", "range", "reversed", "round", "set", "sorted", "str", "sum", "tuple", "zip",
     "isinstance", "divmod", "pow", "iter", "next",
     "True", "False", "None",
     "Exception", "ValueError", "ZeroDivisionError", "ArithmeticError", "KeyError", "IndexError", "TypeError"}
)

NOMES_PROIBIDOS = frozenset(
    {"eval", "exec", "compile", "open", "input", "breakpoint", "globals", "locals", "vars", "getattr",
     "setattr", "delattr", "hasattr", "type", "object", "memoryview", "__import__", "importlib", "super",
     "help", "dir", "print", "exit", "quit", "os", "sys", "subprocess", "socket", "pathlib", "ctypes",
     "pickle", "marshal", "threading", "multiprocessing", "asyncio", "requests", "httpx", "pandas", "numpy",
     "BaseException", "SystemExit", "KeyboardInterrupt"}
)

NOS_PROIBIDOS = (
    ast.ClassDef, ast.AsyncFunctionDef, ast.AsyncFor, ast.AsyncWith, ast.Await, ast.Global, ast.Nonlocal,
    ast.Delete, ast.Yield, ast.YieldFrom, ast.With, ast.Match, ast.NamedExpr,
)

ASSINATURA = ["vendas", "regras", "cenario"]
BUILTINS_PYTHON = frozenset(dir(builtins))


@dataclass
class ResultadoValidacao:
    violacoes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violacoes


def validar_codigo(codigo: str, max_linhas: int, max_bytes: int) -> ResultadoValidacao:
    r = ResultadoValidacao()
    if len(codigo.encode("utf-8")) > max_bytes:
        r.violacoes.append(f"Código acima de {max_bytes} bytes.")
        return r
    if len(codigo.splitlines()) > max_linhas:
        r.violacoes.append(f"Código acima de {max_linhas} linhas.")
        return r
    try:
        arvore = ast.parse(codigo)
    except SyntaxError as exc:
        r.violacoes.append(f"Sintaxe inválida: {exc.msg} (linha {exc.lineno}).")
        return r

    funcoes: dict[str, ast.FunctionDef] = {}
    for no in arvore.body:
        if isinstance(no, (ast.Import, ast.ImportFrom)):
            _checar_import(no, r)
        elif isinstance(no, ast.FunctionDef):
            funcoes[no.name] = no
        elif isinstance(no, (ast.Assign, ast.AnnAssign)):
            pass  # constantes de módulo; o conteúdo é validado na varredura geral
        elif isinstance(no, ast.Expr) and isinstance(no.value, ast.Constant) and isinstance(no.value.value, str):
            pass  # docstring
        else:
            r.violacoes.append(f"Instrução de nível de módulo não permitida (linha {no.lineno}).")

    alvo = funcoes.get("simular")
    if alvo is None:
        r.violacoes.append("Função `simular(vendas, regras, cenario)` ausente.")
    elif [a.arg for a in alvo.args.args] != ASSINATURA or alvo.args.vararg or alvo.args.kwarg or alvo.args.kwonlyargs:
        r.violacoes.append("A assinatura deve ser exatamente `simular(vendas, regras, cenario)`.")

    for no in ast.walk(arvore):
        if isinstance(no, NOS_PROIBIDOS):
            r.violacoes.append(f"Construção não permitida: {type(no).__name__} (linha {getattr(no, 'lineno', '?')}).")
        elif isinstance(no, ast.Attribute) and no.attr.startswith("__"):
            r.violacoes.append(f"Atributo especial proibido: {no.attr} (linha {no.lineno}).")
        elif isinstance(no, ast.Name):
            _checar_nome(no, r)
        elif isinstance(no, ast.ExceptHandler):
            if no.type is None:
                r.violacoes.append(f"`except:` genérico não permitido (linha {no.lineno}).")
        elif isinstance(no, ast.While) and _e_laco_infinito(no):
            r.violacoes.append(f"Laço `while True` sem saída (linha {no.lineno}).")
        elif isinstance(no, (ast.Import, ast.ImportFrom)) and no not in arvore.body:
            _checar_import(no, r)  # imports dentro de função também são checados
        elif isinstance(no, ast.Constant) and isinstance(no.value, int) and abs(no.value) > 10**18:
            r.violacoes.append(f"Constante inteira gigante (linha {no.lineno}).")

    for nome, fn in funcoes.items():
        for no in ast.walk(fn):
            if isinstance(no, ast.Call) and isinstance(no.func, ast.Name) and no.func.id == nome:
                r.violacoes.append(f"Recursão não permitida em `{nome}`.")
                break
    return r


def _checar_import(no: ast.Import | ast.ImportFrom, r: ResultadoValidacao) -> None:
    if isinstance(no, ast.Import):
        modulos = [a.name for a in no.names]
    else:
        if no.level:
            r.violacoes.append("Import relativo não permitido.")
            return
        modulos = [no.module or ""]
        if any(a.name == "*" for a in no.names):
            r.violacoes.append("`import *` não permitido.")
    for m in modulos:
        if m.split(".")[0] not in IMPORTS_PERMITIDOS:
            r.violacoes.append(f"Import não permitido: {m} (linha {no.lineno}).")


def _checar_nome(no: ast.Name, r: ResultadoValidacao) -> None:
    if no.id in NOMES_PROIBIDOS or no.id.startswith("__"):
        r.violacoes.append(f"Nome proibido: {no.id} (linha {no.lineno}).")
    elif isinstance(no.ctx, ast.Load) and no.id in BUILTINS_PYTHON and no.id not in BUILTINS_PERMITIDOS:
        r.violacoes.append(f"Builtin não permitido: {no.id} (linha {no.lineno}).")


def _e_laco_infinito(no: ast.While) -> bool:
    if not (isinstance(no.test, ast.Constant) and no.test.value):
        return False
    return not any(isinstance(n, (ast.Break, ast.Return)) for n in ast.walk(no))
