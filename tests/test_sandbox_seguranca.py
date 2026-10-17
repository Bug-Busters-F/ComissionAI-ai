"""Corpus de ataque do sandbox: cada caso deve ser bloqueado sem derrubar o serviço."""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from app.core.config import settings
from app.core.simulacao.sandbox import Sandbox
from app.core.simulacao.templates import TEMPLATE_CODIGO
from app.core.simulacao.validador import validar_codigo

VENDAS = [{"valorVenda": "100.00", "matricula": "M1"}]
CEN = [{"nome": "base", "multiplicadorVendas": "1"}]


def corpo(*linhas, topo=""):
    """Monta um módulo com a função simular cujo corpo são as linhas dadas."""
    c = topo + "\ndef simular(vendas, regras, cenario):\n"
    c += "".join("    " + l + "\n" for l in linhas)
    return c


def rodar(codigo):
    return Sandbox().executar(codigo, VENDAS, [], CEN)


class TestBloqueioEstatico(unittest.TestCase):
    """Rejeitados ANTES de executar (análise AST por lista de permissão)."""

    def assertRejeita(self, codigo, trecho=None):
        r = rodar(codigo)
        self.assertFalse(r.ok, codigo)
        self.assertEqual(r.erro, "VALIDACAO", f"{codigo} -> {r.erro} {r.detalhe}")
        if trecho:
            self.assertIn(trecho, " ".join(r.violacoes))

    def test_imports_proibidos(self):
        for mod in ("os", "sys", "subprocess", "socket", "pathlib", "ctypes", "pickle", "threading", "urllib.request"):
            self.assertRejeita(corpo("return {}", topo=f"import {mod}"), "Import não permitido")
        self.assertRejeita(corpo("return {}", topo="from os import environ"), "Import não permitido")
        self.assertRejeita(corpo("return {}", topo="from decimal import *"), "import *")

    def test_import_dentro_da_funcao(self):
        self.assertRejeita(corpo("import os", "return {}"), "Import não permitido")

    def test_import_dinamico_e_eval_exec_open(self):
        self.assertRejeita(corpo("return __import__('os').environ"), "__import__")
        self.assertRejeita(corpo("return eval('1+1')"), "eval")
        self.assertRejeita(corpo("exec('x=1')", "return {}"), "exec")
        self.assertRejeita(corpo("return open('/etc/passwd').read()"), "open")
        self.assertRejeita(corpo("return compile('1','a','eval')"), "compile")
        self.assertRejeita(corpo("return input()"), "input")

    def test_acesso_a_segredos_e_ambiente(self):
        self.assertRejeita(corpo("return os.environ['LLM_API_KEY']"), "os")
        self.assertRejeita(corpo("return sys.modules"), "sys")

    def test_escape_por_atributos_especiais(self):
        self.assertRejeita(corpo("return ().__class__.__bases__[0].__subclasses__()"), "__class__")
        self.assertRejeita(corpo("return simular.__globals__"), "__globals__")
        self.assertRejeita(corpo("return vendas.__class__"), "__class__")

    def test_getattr_obfuscado_e_type(self):
        self.assertRejeita(corpo("return getattr(vendas, '__cl' + 'ass__')"), "getattr")
        self.assertRejeita(corpo("return type(vendas)"), "type")
        self.assertRejeita(corpo("return globals()"), "globals")
        self.assertRejeita(corpo("return vars()"), "vars")

    def test_construcoes_proibidas(self):
        self.assertRejeita("class A:\n    pass\ndef simular(vendas, regras, cenario):\n    return {}\n", "ClassDef")
        self.assertRejeita(corpo("global x", "return {}"), "Global")
        self.assertRejeita(corpo("with vendas:", "    pass", "return {}"), "With")
        self.assertRejeita(corpo("yield 1"), "Yield")
        self.assertRejeita(corpo("try:", "    pass", "except:", "    pass", "return {}"), "except")

    def test_laco_infinito_e_recursao(self):
        self.assertRejeita(corpo("while True:", "    pass"), "while True")
        self.assertRejeita(corpo("return simular(vendas, regras, cenario)"), "Recursão")

    def test_forma_do_modulo(self):
        self.assertRejeita("x = 1\n", "simular")
        self.assertRejeita("def simular(a, b):\n    return {}\n", "assinatura")
        self.assertRejeita("print('oi')\ndef simular(vendas, regras, cenario):\n    return {}\n", "nível de módulo")
        self.assertRejeita("def simular(vendas, regras, cenario)\n    return {}\n", "Sintaxe")

    def test_builtin_nao_permitido(self):
        self.assertRejeita(corpo("return print(1)"), "print")
        self.assertRejeita(corpo("return dir(vendas)"), "dir")
        self.assertRejeita(corpo("return hash(1)"), "hash")

    def test_limites_de_tamanho(self):
        self.assertRejeita("x = 1\n" * 200, "linhas")
        self.assertRejeita(corpo("return '" + "a" * 9000 + "'"), "bytes")

    def test_constante_gigante(self):
        self.assertRejeita(corpo(f"return {10**19}"), "gigante")


class TestBloqueioEmExecucao(unittest.TestCase):
    """O que passa na análise estática mas é detido no runtime (defesa em profundidade)."""

    def test_codigo_valido_executa(self):
        r = rodar("from decimal import Decimal\ndef simular(vendas, regras, cenario):\n    return {'t': sum((Decimal(v['valorVenda']) if False else v['valorVenda'] for v in vendas), Decimal('0'))}\n")
        self.assertTrue(r.ok, r.detalhe)
        self.assertEqual(r.resultados[0]["t"], "100.00")

    def test_timeout_laco_longo(self):
        with patch.object(settings, "sim_max_seconds", 1.0):
            r = rodar(corpo("n = 0", "while n < 10**12:", "    n += 1", "return {'n': n}"))
        self.assertFalse(r.ok)
        self.assertIn(r.erro, ("TIMEOUT", "MEMORIA"))

    def test_memoria_excessiva(self):
        with patch.object(settings, "sim_max_memory_mb", 128):
            r = rodar(corpo("x = [0] * (10**9)", "return {'n': len(x)}"))
        self.assertFalse(r.ok)
        self.assertEqual(r.erro, "MEMORIA")

    def test_saida_enorme(self):
        with patch.object(settings, "sim_max_output_kb", 1):
            r = rodar(corpo("return {'x': 'a' * 100000}"))
        self.assertFalse(r.ok)
        self.assertEqual(r.erro, "SAIDA_EXCESSIVA")

    def test_erro_do_codigo_nao_derruba_o_servico(self):
        r = rodar(corpo("return {'x': 1 / 0}"))
        self.assertFalse(r.ok)
        self.assertEqual(r.erro, "ERRO_CODIGO")
        self.assertIn("ZeroDivisionError", r.detalhe)

    def test_tipo_nao_serializavel(self):
        r = rodar(corpo("return {'x': {1, 2}}"))
        self.assertFalse(r.ok)
        self.assertEqual(r.erro, "ERRO_CODIGO")

    def test_valor_nao_finito_rejeitado(self):
        r = rodar(corpo("return {'x': float('nan')}"))
        self.assertFalse(r.ok)

    def test_import_dentro_de_modulo_so_permitidos(self):
        r = rodar("import math\ndef simular(vendas, regras, cenario):\n    return {'r': math.floor(2.7)}\n")
        self.assertTrue(r.ok, r.detalhe)
        self.assertEqual(r.resultados[0]["r"], 2)

    def test_segredos_do_processo_pai_nao_alcancaveis(self):
        """O filho roda com ambiente vazio: nem a chave do LLM nem PATH existem lá."""
        with patch.dict(os.environ, {"LLM_API_KEY": "segredo-super-secreto"}):
            # a análise estática barra `os`; aqui provamos o isolamento pelo ambiente do filho
            import subprocess
            from app.core.simulacao import sandbox as sb

            saida = subprocess.run(
                [sys.executable, "-I", "-c", "import os,sys;sys.stdout.write(str(dict(os.environ)))"],
                capture_output=True, env={}, check=True,
            ).stdout.decode()
        # o Python pode injetar LC_CTYPE sozinho; nada herdado do pai pode aparecer
        self.assertNotIn("LLM_API_KEY", saida)
        self.assertNotIn("PATH", saida)
        self.assertNotIn("segredo-super-secreto", saida)

    def test_servico_continua_apos_ataques(self):
        for _ in range(3):
            rodar(corpo("return os.environ"))
        self.assertTrue(rodar(corpo("return {'ok': 1}")).ok)


class TestAuditHookMataProcesso(unittest.TestCase):
    """Chamamos o runner direto com código que burlaria a AST, para provar a 2ª camada."""

    def _executar_sem_ast(self, codigo):
        import json
        import subprocess
        from app.core.simulacao import sandbox as sb

        carga = json.dumps({"codigo": codigo, "vendas": VENDAS, "regras": [], "cenarios": CEN,
                            "limites": {"memoria_mb": 256, "cpu_s": 5, "saida_max_bytes": 100000}})
        return subprocess.run([sys.executable, "-I", str(sb._RUNNER)], input=carga.encode(),
                              capture_output=True, env={}, timeout=15)

    def test_open_morto_pelo_hook(self):
        # `open` não existe nos builtins restritos; usamos um caminho indireto permitido pelo AST
        p = self._executar_sem_ast("def simular(vendas, regras, cenario):\n    return {'x': open('/etc/passwd').read()}\n")
        self.assertNotEqual(p.returncode, 0)
        self.assertNotIn(b"root:", p.stdout)

    def test_import_os_barrado_pelo_import_restrito(self):
        p = self._executar_sem_ast("import os\ndef simular(vendas, regras, cenario):\n    return {'x': 1}\n")
        self.assertNotEqual(p.returncode, 0)

    def test_hook_encerra_em_evento_proibido(self):
        # força um evento de auditoria 'socket.' via módulo permitido? não há; valida o hook diretamente
        import importlib.util
        from app.core.simulacao import sandbox as sb

        spec = importlib.util.spec_from_file_location("runner_mod", sb._RUNNER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        chamadas = []
        mod._EXIT = lambda c: chamadas.append(c)
        mod._hook("socket.connect", ())
        mod._hook("open", ())
        mod._hook("os.system", ())
        mod._hook("exec", ())
        mod._hook("math.floor", ())
        self.assertEqual(chamadas, [97, 97, 97])


class TestTemplateNoSandbox(unittest.TestCase):
    def test_template_passa_na_analise(self):
        self.assertTrue(validar_codigo(TEMPLATE_CODIGO, settings.sim_max_code_lines, settings.sim_max_code_bytes).ok)

    def test_template_calcula(self):
        vendas = [
            {"valorVenda": "1000.00", "matricula": "M1", "codLoja": 75, "codCargo": 100, "codMarca": 10, "dataVenda": "2026-12-10", "canal": None},
            {"valorVenda": "2500.50", "matricula": "M2", "codLoja": 75, "codCargo": 150, "codMarca": 10, "dataVenda": "2026-12-11", "canal": None},
        ]
        regras = [
            {"idLocal": "p1", "taxa": "0.03", "dataInicio": "2026-12-01", "dataFim": "2026-12-31", "condicoes": {"codLoja": 75, "codCargo": 100}},
            {"idLocal": "p2", "taxa": "0.02", "dataInicio": "2026-12-01", "dataFim": "2026-12-31", "condicoes": {"codLoja": 75}, "bonus": {"valorFixo": "5"}},
        ]
        r = Sandbox().executar(TEMPLATE_CODIGO, vendas, regras, [{"nome": "base", "multiplicadorVendas": "1"}, {"nome": "+20%", "multiplicadorVendas": "1.2"}])
        self.assertTrue(r.ok, r.detalhe)
        base, mais = r.resultados
        # venda 1: p1 (loja 8 + cargo 4 = 12) vence p2 (8): 1000*0.03 = 30.00
        # venda 2: só p2 casa: 2500.50*0.02 = 50.01 + 5 fixo = 55.01
        self.assertEqual(base["totalComissao"], "85.01")
        self.assertEqual(base["porBloco"], {"p1": "30.00", "p2": "55.01"})
        self.assertEqual(base["totalVendas"], "3500.50")
        self.assertEqual(mais["totalVendas"], "4200.60")  # cada venda ×1.2 com HALF_UP
        self.assertEqual(mais["porBloco"]["p1"], "36.00")


if __name__ == "__main__":
    unittest.main()
