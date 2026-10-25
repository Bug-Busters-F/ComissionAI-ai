"""Construção de pendências tipadas (catálogo fechado) a partir de textos dos normalizadores."""

from app.schemas.proposta import CodigoPendencia, Pendencia


def pendencia(codigo: CodigoPendencia, mensagem: str, campo: str | None = None, pergunta: str | None = None) -> Pendencia:
    return Pendencia(codigo=codigo, mensagem=mensagem, campo=campo, pergunta=pergunta)


def pendencia_de_texto(mensagem: str, campo: str | None = None) -> Pendencia:
    """Classifica a mensagem dos normalizadores existentes no catálogo de códigos."""
    m = mensagem.lower()
    if "ambiguidade de cargo" in m:
        codigo = CodigoPendencia.AMBIGUIDADE_CARGO
    elif "ambigu" in m:
        codigo = CodigoPendencia.AMBIGUIDADE_PUBLICO
    elif "não encontrad" in m or "nao encontrad" in m or "não é reconhecido" in m:
        codigo = CodigoPendencia.CADASTRO_INEXISTENTE
    elif campo == "taxa" and ("não identificado" in m or "vazio" in m):
        codigo = CodigoPendencia.CAMPO_AUSENTE
    elif campo == "taxa":
        codigo = CodigoPendencia.TAXA_INVALIDA
    elif "não identificad" in m or "não informad" in m:
        codigo = CodigoPendencia.CAMPO_AUSENTE
    elif "vigência" in m or "data de término" in m or "mês de término" in m:
        codigo = CodigoPendencia.VIGENCIA_INCOMPATIVEL
    else:
        codigo = CodigoPendencia.CAMPO_AUSENTE
    return Pendencia(codigo=codigo, mensagem=mensagem, campo=campo)
