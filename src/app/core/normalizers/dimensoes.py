"""
Normalizador determinístico de dimensões de negócio: marca, loja e cargo (Task S1-A04).

Este módulo resolve os termos brutos extraídos pelo LLM (ex: 'PRETO', '75', 'vendedores')
para os respectivos códigos numéricos e descrições canônicas presentes no catálogo
`dicionario_dimensoes` enviado pelo Backend no contexto da requisição.

Estratégia de match:
- Normalização: strip + upper + remoção de acentos + colapso de espaços.
- Match exato após normalização: sem fuzzy matching ou substring para evitar
  correspondências incorretas.
- Para cargo: `codCargo` e `descriCargo` são resolvidos em conjunto, pois um mesmo
  código pode mapear funções distintas (ex: 150 → "GERENTE DE LOJA" ou "GERENTE QUIOSQUE").
  Quando há múltiplos candidatos, retorna None para ambos e gera pendência.
- Loja: resolvida por código numérico — o LLM extrai "75" ou "loja 75" e o normalizer
  extrai o inteiro do texto.
"""

import re
import unicodedata
from typing import Any


# ---------------------------------------------------------------------------
# Utilitários internos
# ---------------------------------------------------------------------------


def _normalizar_texto(texto: str) -> str:
    """Remove acentos, converte para maiúsculo e colapsa espaços extras."""
    nfkd = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem_acento.strip().upper())


def _extrair_dicionario_dimensoes(contexto: dict[str, Any] | None) -> dict[str, Any]:
    """Extrai o `dicionario_dimensoes` do contexto, retornando dict vazio se ausente."""
    if contexto and isinstance(contexto.get("dicionario_dimensoes"), dict):
        return contexto["dicionario_dimensoes"]
    return {}


# ---------------------------------------------------------------------------
# Normalização de Marca
# ---------------------------------------------------------------------------


def normalizar_marca(
    marca_raw: str | None,
    contexto: dict[str, Any] | None = None,
) -> tuple[int | None, str | None, list[str]]:
    """
    Resolve o termo bruto de marca para (codMarca, descrMarca) usando o catálogo.

    Args:
        marca_raw: Texto extraído pelo LLM (ex: 'PRETO', 'marca Branco').
        contexto: Contexto da requisição, pode conter `dicionario_dimensoes.marcas`.

    Returns:
        Tupla (cod_marca, descr_marca, pendencias).
        - Se encontrado: (int, str, [])
        - Se não encontrado ou não informado: (None, None, []) ou (None, None, [msg])
    """
    pendencias: list[str] = []

    if not marca_raw or not marca_raw.strip():
        return None, None, pendencias

    dim = _extrair_dicionario_dimensoes(contexto)
    marcas: dict[str, str] = dim.get("marcas", {})

    if not marcas:
        # Sem catálogo — não é possível resolver o código; retorna None sem pendência
        # (o backend pode gerar pendência se necessar o vínculo).
        return None, None, pendencias

    marca_normalizada = _normalizar_texto(marca_raw)

    # Remover prefixos comuns como "MARCA " antes de comparar
    marca_comparacao = re.sub(r"^MARCA\s+", "", marca_normalizada)

    # Busca no catálogo (chave=código, valor=nome)
    for cod_str, nome in marcas.items():
        nome_normalizado = _normalizar_texto(str(nome))
        if nome_normalizado == marca_comparacao:
            try:
                return int(cod_str), nome_normalizado, pendencias
            except ValueError:
                # Código não numérico no catálogo — ignora
                pass

    # Nenhuma correspondência exata encontrada
    pendencias.append(
        f"Marca '{marca_raw}' não encontrada no catálogo de marcas disponíveis."
    )
    return None, None, pendencias


# ---------------------------------------------------------------------------
# Normalização de Loja
# ---------------------------------------------------------------------------


def normalizar_loja(
    loja_raw: str | None,
) -> tuple[int | None, list[str]]:
    """
    Resolve o termo bruto de loja para o código numérico inteiro.

    A loja é identificada pelo código numérico apenas — não há catálogo de nomes de loja
    no contrato atual. O LLM extrai expressões como '75' ou 'loja 75'.

    Args:
        loja_raw: Texto extraído pelo LLM (ex: '75', 'loja 35').

    Returns:
        Tupla (cod_loja, pendencias).
    """
    pendencias: list[str] = []

    if not loja_raw or not loja_raw.strip():
        return None, pendencias

    # Extrai sequência numérica da expressão (ex: 'loja 75' → '75')
    match = re.search(r"\d+", loja_raw.strip())
    if match:
        return int(match.group()), pendencias

    pendencias.append(
        f"Não foi possível extrair o código numérico da loja a partir de '{loja_raw}'."
    )
    return None, pendencias


# ---------------------------------------------------------------------------
# Normalização de Cargo
# ---------------------------------------------------------------------------


def _parse_cod(cod_val: Any) -> int | None:
    """Extrai inteiro de chave numérica ou composta (ex: 150 ou '150_2')."""
    try:
        return int(cod_val)
    except (ValueError, TypeError):
        m = re.match(r"^(\d+)", str(cod_val))
        if m:
            return int(m.group(1))
        return None


def normalizar_cargo(
    cargo_raw: str | None,
    contexto: dict[str, Any] | None = None,
) -> tuple[int | None, str | None, list[str]]:
    """
    Resolve o termo bruto de cargo para (codCargo, descriCargo) usando o catálogo.

    Regras de resolução:
    - Se houver correspondência unívoca: retorna (codCargo, descriCargo, []).
    - Se houver ambiguidade de funções que compartilham o mesmo código numérico
      (ex: 150 para 'GERENTE DE LOJA' e 'GERENTE QUIOSQUE' conforme Cenário C do contrato):
      retorna (codCargo, None, [pendencia_ambiguidade]).
    - Se houver múltiplos candidatos com códigos distintos ou nenhuma correspondência:
      retorna (None, None, [pendencia]).

    Args:
        cargo_raw: Texto extraído pelo LLM (ex: 'vendedores', 'gerentes', 'GERENTE DE LOJA').
        contexto: Contexto da requisição, pode conter `dicionario_dimensoes.cargos`.

    Returns:
        Tupla (cod_cargo, descri_cargo, pendencias).
    """
    pendencias: list[str] = []

    if not cargo_raw or not cargo_raw.strip():
        return None, None, pendencias

    dim = _extrair_dicionario_dimensoes(contexto)
    cargos = dim.get("cargos", {})

    if not cargos:
        # Sem catálogo — não é possível resolver o código.
        return None, None, pendencias

    itens_cargos: list[tuple[int, str]] = []
    if isinstance(cargos, dict):
        for cod_key, nome in cargos.items():
            parsed_cod = _parse_cod(cod_key)
            if parsed_cod is not None and nome:
                itens_cargos.append((parsed_cod, _normalizar_texto(str(nome))))
    elif isinstance(cargos, list):
        for item in cargos:
            if isinstance(item, dict):
                cod_val = item.get("codCargo") or item.get("codigo") or item.get("cod")
                nome_val = item.get("descriCargo") or item.get("descricao") or item.get("nome")
                parsed_cod = _parse_cod(cod_val)
                if parsed_cod is not None and nome_val:
                    itens_cargos.append((parsed_cod, _normalizar_texto(str(nome_val))))

    if not itens_cargos:
        return None, None, pendencias

    cargo_normalizado = _normalizar_texto(cargo_raw)
    cargo_limpo = re.sub(r"^CARGO\s+", "", cargo_normalizado)

    # 1. Match exato
    candidatos_exatos = [(cod, nome) for cod, nome in itens_cargos if nome == cargo_limpo]
    if len(candidatos_exatos) == 1:
        return candidatos_exatos[0][0], candidatos_exatos[0][1], pendencias

    if len(candidatos_exatos) > 1:
        candidatos = candidatos_exatos
    else:
        # 2. Match flexível (singular/plural e termos contidos)
        cargo_stem = re.sub(r"(ES|S)\b", "", cargo_limpo)
        candidatos = []
        for cod, nome in itens_cargos:
            nome_stem = re.sub(r"(ES|S)\b", "", nome)
            if (
                cargo_limpo in nome
                or (len(cargo_stem) >= 4 and cargo_stem in nome_stem)
                or all(w in nome.split() for w in cargo_limpo.split())
            ):
                candidatos.append((cod, nome))

    if len(candidatos) == 1:
        cod, nome = candidatos[0]
        return cod, nome, pendencias

    if len(candidatos) > 1:
        codigos = {cod for cod, _ in candidatos}
        nomes_formatados = " ou ".join(f"'{n}'" for _, n in candidatos)
        pendencias.append(
            f"Ambiguidade de cargo: '{cargo_raw}' pode referir-se a {nomes_formatados}."
        )
        if len(codigos) == 1:
            # Todos os candidatos compartilham o mesmo código numérico (Cenário C do contrato)
            return codigos.pop(), None, pendencias
        else:
            return None, None, pendencias

    # Nenhum candidato encontrado
    pendencias.append(
        f"Cargo '{cargo_raw}' não encontrado no catálogo de cargos disponíveis."
    )
    return None, None, pendencias
