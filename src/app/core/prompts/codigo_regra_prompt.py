"""
Gerador de código Python por regra de proposta (IA-7 / BUG-58).

Modelo controlado (não gerado por LLM): o código é o motor de `TEMPLATE_CODIGO` (o mesmo usado em
/api/v2/simular e validado pelos casos de ouro do Spring) com a regra do bloco embutida como dado.
Assim a precedência, as faixas inclusivas/exclusivas e o arredondamento são idênticos por construção.

Uso no sandbox: `simular(vendas, regras, cenario)`, onde `regras` são as DEMAIS regras da proposta.
- Sem demais regras: calcula só esta regra; venda fora do público fica em `vendasSemRegra`
  (no Spring ela cairia em outra regra ou na base de comissão).
- Com as demais regras: reproduz a escolha da regra vencedora entre todas, como o template.
Todos os valores do bloco entram como literais escapados (`repr`), nunca por interpolação de texto.
"""

import logging
from decimal import Decimal
from typing import Any

from app.core.config import settings
from app.core.simulacao.templates import TEMPLATE_CODIGO
from app.core.simulacao.validador import validar_codigo
from app.schemas.proposta import BlocoProposta

logger = logging.getLogger(__name__)

_ASSINATURA_TEMPLATE = "def simular(vendas, regras, cenario):"
# motor do template sem linhas em branco (cabe no limite de linhas do validador)
_MOTOR = "\n".join(
    linha for linha in TEMPLATE_CODIGO.replace(_ASSINATURA_TEMPLATE, "def _simular_motor(vendas, regras, cenario):")
    .splitlines()
    if linha.strip()
)

_INVOLUCRO = '''
def simular(vendas, regras, cenario):
    outras = [r for r in (regras or []) if r.get("idLocal") != REGRA["idLocal"]]
    return _simular_motor(vendas, outras + [REGRA], cenario)
'''


def regra_como_dict(bloco: BlocoProposta) -> dict[str, Any]:
    """
    Representação da regra no formato do motor de simulação (mesmos campos do sandbox).

    Args:
        bloco: Bloco de proposta.

    Returns:
        Dicionário com idLocal, taxa, bônus, vigência e condições.
    """
    c = bloco.condicoes
    faixa = None
    if c.faixaValor:
        f = c.faixaValor
        faixa = {"min": f.min, "max": f.max, "minInclusivo": f.minInclusivo, "maxInclusivo": f.maxInclusivo}
    bonus = None
    if bloco.bonus:
        bonus = {"percentual": bloco.bonus.percentual, "valorFixo": bloco.bonus.valorFixo}
    return {
        "idLocal": bloco.idLocal,
        "taxa": bloco.taxa,
        "bonus": bonus,
        "dataInicio": bloco.dataInicio.isoformat() if bloco.dataInicio else None,
        "dataFim": bloco.dataFim.isoformat() if bloco.dataFim else None,
        "condicoes": {
            "canal": c.canal, "codMarca": c.codMarca, "codCargo": c.codCargo, "codLoja": c.codLoja,
            "matricula": c.matricula, "faixaValor": faixa,
        },
    }


def gerar_codigo_regra(bloco: BlocoProposta) -> str | None:
    """
    Gera o Python equivalente da regra e o valida com a mesma análise estática do sandbox.

    Args:
        bloco: Bloco de proposta com os campos atuais.

    Returns:
        Código validado, ou None se a validação falhar (o código inválido nunca é devolvido).
    """
    codigo = (
        f"# Regra {bloco.idLocal!r}: código gerado a partir dos campos atuais da proposta.\n"
        f"{_MOTOR}\n"
        f"REGRA = {_literal(regra_como_dict(bloco))}\n"
        f"{_INVOLUCRO}"
    ).strip() + "\n"
    validacao = validar_codigo(
        codigo,
        max_linhas=settings.sim_max_code_lines,
        max_bytes=settings.sim_max_code_bytes,
    )
    if not validacao.ok:
        logger.error("Código da regra %r rejeitado pela validação: %s", bloco.idLocal, validacao.violacoes)
        return None
    return codigo


def _literal(valor: Any) -> str:
    """Literal Python seguro para os tipos da regra (strings sempre via repr)."""
    if valor is None or isinstance(valor, bool):
        return repr(valor)
    if isinstance(valor, Decimal):
        return f"Decimal({str(valor)!r})"
    if isinstance(valor, (int, str)):
        return repr(valor)
    if isinstance(valor, dict):
        return "{" + ", ".join(f"{str(k)!r}: {_literal(v)}" for k, v in valor.items()) + "}"
    raise TypeError(f"Tipo não suportado na regra: {type(valor).__name__}")
