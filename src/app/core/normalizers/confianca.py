"""
Cálculo determinístico do nível de confiança da interpretação (Task S1-A04).

A confiança (0.00 a 1.00) é calculada de forma 100% determinística em Python,
com critérios explícitos, documentados e testáveis baseados em:
1. Completude dos campos essenciais (taxa, canal, dataInicio);
2. Consistência e integridade temporal;
3. Penalizações por menção a dimensões não suportadas no MVP;
4. Penalizações por ambiguidades e pendências de normalização.

O LLM não arbitra a pontuação final de confiança.
"""

from decimal import Decimal
from datetime import date


def calcular_confianca(
    taxa: Decimal | None,
    canal: str | None,
    data_inicio: date | None,
    data_fim: date | None,
    criterios_nao_suportados: list[str] | None = None,
    ambiguidades: list[str] | None = None,
    pendencias_normalizacao: list[str] | None = None,
) -> Decimal:
    """
    Calcula deterministicamente o score de confiança técnica da interpretação.

    Pesos base:
    - Taxa válida: +0.40
    - Canal válido: +0.35
    - Data de início válida: +0.25
    Total máximo de base: 1.00

    Penalizações:
    - Dimensões não suportadas (loja, marca, cargo, etc.): -0.20 por ocorrência
    - Ambiguidades identificadas: -0.15 por ocorrência
    - Erros de normalização/pendências estruturais: -0.15 por ocorrência

    Returns:
        Decimal quantizado em 2 casas decimais no intervalo [0.00, 1.00].
    """
    score = Decimal("0.00")

    # 1. Completude de campos essenciais
    if taxa is not None:
        score += Decimal("0.40")

    if canal is not None:
        score += Decimal("0.35")

    if data_inicio is not None:
        score += Decimal("0.25")

    # 2. Consistência de vigência (se fim for anterior a início, penaliza severamente)
    if data_inicio is not None and data_fim is not None:
        if data_fim < data_inicio:
            score -= Decimal("0.30")

    # 3. Penalização por critérios não suportados no MVP
    if criterios_nao_suportados:
        score -= Decimal("0.20") * len(criterios_nao_suportados)

    # 4. Penalização por ambiguidades textuais
    if ambiguidades:
        score -= Decimal("0.15") * len(ambiguidades)

    # 5. Penalização por pendências de normalização
    if pendencias_normalizacao:
        score -= Decimal("0.15") * len(pendencias_normalizacao)

    # Limitar ao intervalo [0.00, 1.00]
    if score < Decimal("0.00"):
        score = Decimal("0.00")
    elif score > Decimal("1.00"):
        score = Decimal("1.00")

    return score.quantize(Decimal("0.01"))
