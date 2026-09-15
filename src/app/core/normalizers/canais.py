"""
Normalizador e validador determinístico de canal de vendas (Task S1-A04).

Converte expressões textuais de canal (ex.: 'ecommerce', 'loja física', 'whatsapp') para
o identificador padronizado em caixa alta e valida contra a lista de canais suportados
ou fornecidos no catálogo/contexto da requisição.
"""

from typing import Any
import unicodedata

CANAIS_PADRAO_MVP = [
    "ECOMMERCE",
    "LOJA_FISICA",
    "WHATSAPP",
    "TELEVENDAS",
    "BALCAO",
]

MAPA_SINONIMOS_CANAIS = {
    "ECOMMERCE": "ECOMMERCE",
    "E COMMERCE": "ECOMMERCE",
    "E-COMMERCE": "ECOMMERCE",
    "ONLINE": "ECOMMERCE",
    "SITE": "ECOMMERCE",
    "LOJA FISICA": "LOJA_FISICA",
    "LOJA_FISICA": "LOJA_FISICA",
    "LOJA": "LOJA_FISICA",
    "PRESENCIAL": "LOJA_FISICA",
    "WHATSAPP": "WHATSAPP",
    "WPP": "WHATSAPP",
    "ZAP": "WHATSAPP",
    "TELEVENDAS": "TELEVENDAS",
    "TELEMARKETING": "TELEVENDAS",
    "TELEFONE": "TELEVENDAS",
    "BALCAO": "BALCAO",
}


def _normalizar_string(texto: str) -> str:
    """Remove acentos, converte para maiúsculo e limpa espaços extras."""
    nfkd = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join([c for c in nfkd if not unicodedata.combining(c)])
    return sem_acento.strip().upper()


def _obter_canais_permitidos(contexto: dict[str, Any] | None) -> list[str]:
    """Extrai lista de canais permitidos do contexto.

    Ordem de prioridade:
    1. `contexto.dicionario_dimensoes.canais` — catálogo enviado pelo Backend (novo contrato).
    2. `contexto.canais_permitidos` — chave legada direta.
    3. `contexto.canais_disponiveis` — chave legada direta.
    4. `contexto.catalogo.canais` — catálogo aninhado legado.
    5. `CANAIS_PADRAO_MVP` — fallback interno quando nenhum catálogo for fornecido.
    """
    if contexto:
        # 1. Novo contrato: dicionario_dimensoes.canais
        dim = contexto.get("dicionario_dimensoes")
        if isinstance(dim, dict) and isinstance(dim.get("canais"), list):
            return [str(c).upper() for c in dim["canais"]]

        # 2-3. Chaves legadas diretas
        if "canais_permitidos" in contexto and isinstance(contexto["canais_permitidos"], list):
            return [str(c).upper() for c in contexto["canais_permitidos"]]
        if "canais_disponiveis" in contexto and isinstance(contexto["canais_disponiveis"], list):
            return [str(c).upper() for c in contexto["canais_disponiveis"]]

        # 4. Catálogo aninhado legado
        if "catalogo" in contexto and isinstance(contexto["catalogo"], dict):
            if "canais" in contexto["catalogo"] and isinstance(contexto["catalogo"]["canais"], list):
                return [
                    c.get("nome", "").upper() if isinstance(c, dict) else str(c).upper()
                    for c in contexto["catalogo"]["canais"]
                ]

    return CANAIS_PADRAO_MVP


def normalizar_canal(
    canal_raw: str | None,
    contexto: dict[str, Any] | None = None,
) -> tuple[str | None, list[str]]:
    """
    Normaliza o canal de venda e valida contra a lista de canais aceitos no MVP.

    Args:
        canal_raw: Texto do canal extraído pelo LLM (ex: 'ecommerce', 'loja física').
        contexto: Metadados contextuais contendo canal_padrao ou canais disponíveis.

    Returns:
        Tupla (canal_normalizado, pendencias).
    """
    pendencias: list[str] = []
    canais_permitidos = _obter_canais_permitidos(contexto)

    # 1. Se canal_raw for None ou vazio, tenta utilizar canal_padrao do contexto
    if not canal_raw or not canal_raw.strip():
        if contexto and "canal_padrao" in contexto and contexto["canal_padrao"]:
            canal_padrao = _normalizar_string(str(contexto["canal_padrao"]))
            if canal_padrao in canais_permitidos:
                return canal_padrao, pendencias
            else:
                pendencias.append(
                    f"Canal padrão contextual '{canal_padrao}' não é permitido no catálogo."
                )
                return None, pendencias

        # canal é opcional/nullable no novo contrato (tb_regra.canal NULLABLE).
        # Se não informado e sem canal_padrao, retorna None sem gerar pendência.
        return None, pendencias

    # 2. Normalizar texto e resolver sinônimos
    c_limpo = _normalizar_string(canal_raw)
    canal_candidato = MAPA_SINONIMOS_CANAIS.get(c_limpo, c_limpo)

    # 3. Validar se está na lista de canais suportados
    if canal_candidato in canais_permitidos:
        return canal_candidato, pendencias

    # Se não foi encontrado
    pendencias.append(
        f"Canal de vendas '{canal_raw}' não é reconhecido no MVP. Canais aceitos: {', '.join(canais_permitidos)}."
    )
    return None, pendencias
