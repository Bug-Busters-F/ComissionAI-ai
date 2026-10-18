"""
Extração de campanhas com várias regras (Sprint 2, IA-2 / BUG-53).

Pipeline: prompt → LLM (extração bruta por regra) → normalização determinística →
validação do trecho de origem → vigência herdada da campanha → cobertura do texto.
Nada é descartado em silêncio: o que não vira regra vai para `trechosNaoMapeados`.
"""

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from app.core.exceptions import LLMResponseParsingError
from app.core.llm_retry import completar_com_retry
from app.core.normalizers.canais import normalizar_canal
from app.core.normalizers.confianca import calcular_confianca
from app.core.normalizers.datas import normalizar_datas
from app.core.normalizers.dimensoes import normalizar_cargo, normalizar_loja, normalizar_marca
from app.core.normalizers.faixas import normalizar_faixa, normalizar_valor_monetario
from app.core.normalizers.taxa import normalizar_taxa
from app.core.pendencias import pendencia, pendencia_de_texto
from app.core.prompts.campanha_prompt import montar_prompt_campanha
from app.providers.base import LLMProvider
from app.schemas.proposta import (
    BlocoProposta,
    Bonus,
    CodigoPendencia,
    Condicoes,
    InterpretarRequestV2,
    Operacao,
    Origem,
    Pendencia,
)
from app.schemas.raw import InterpretacaoCampanhaRawLLM, RegraRawLLM

logger = logging.getLogger(__name__)

_MATRICULA = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-./]*$")


@dataclass
class BlocoInterno:
    """Bloco + os termos brutos que o agente ainda pode resolver com ferramentas."""

    bloco: BlocoProposta
    raw: RegraRawLLM
    # dimensões cujo termo existe mas o código não foi resolvido pelo catálogo local
    lacunas_cadastro: set[str] = field(default_factory=set)


@dataclass
class ResultadoExtracao:
    blocos: list[BlocoInterno]
    pendencias_gerais: list[Pendencia]
    trechos_nao_mapeados: list[Origem]
    contexto_normalizacao: dict[str, Any]


def _sem_acento(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def localizar_trecho(texto: str, trecho: str) -> tuple[int, int] | None:
    """Localiza o trecho no texto, tolerando caixa e variação de espaços. None se não existir."""
    trecho = trecho.strip()
    if not trecho:
        return None
    exato = texto.find(trecho)
    if exato >= 0:
        return exato, exato + len(trecho)
    partes = [re.escape(p) for p in trecho.split()]
    if not partes:
        return None
    m = re.search(r"\s+".join(partes), texto, flags=re.IGNORECASE)
    if m:
        return m.start(), m.end()
    return None


def normalizar_matricula(raw: str | None) -> tuple[str | None, list[str]]:
    if raw is None or not raw.strip():
        return None, []
    limpa = re.sub(r"^(matr[ií]cula|matr\.)\s*[:#]?\s*", "", raw.strip(), flags=re.IGNORECASE) or raw.strip()
    limpa = re.sub(r"\s+", "", limpa).upper()
    if not _MATRICULA.match(limpa):
        return None, [f"Matrícula inválida: '{raw}'."]
    return limpa, []


class ExtratorCampanha:
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    # ------------------------------------------------------------------ público
    def extrair(self, request: InterpretarRequestV2) -> ResultadoExtracao:
        texto = request.texto.strip()
        ref = request.dataReferencia or date.today()
        contexto: dict[str, Any] = {
            "ano_referencia": ref.year,
            "data_referencia": ref.isoformat(),
            "dicionario_dimensoes": _catalogo_como_dimensoes(request.catalogo),
        }
        if request.catalogo.get("canal_padrao"):
            contexto["canal_padrao"] = request.catalogo["canal_padrao"]

        prompt = montar_prompt_campanha(texto, contexto)
        schema = InterpretacaoCampanhaRawLLM.model_json_schema()
        raw_dict = completar_com_retry(self._provider, prompt, schema)
        try:
            raw = InterpretacaoCampanhaRawLLM.model_validate(raw_dict)
        except ValidationError as exc:
            raise LLMResponseParsingError(f"Estrutura bruta inválida retornada pelo LLM: {exc}") from exc

        vigencia_base, pend_vigencia_base = self._vigencia_base(request, raw, contexto)
        blocos: list[BlocoInterno] = []
        spans: list[tuple[int, int]] = []
        for i, regra in enumerate(raw.regras, 1):
            interno = self._montar_bloco(f"p{i}", regra, texto, contexto, vigencia_base)
            blocos.append(interno)
            if interno.bloco.origem and interno.bloco.origem.inicio is not None:
                spans.append((interno.bloco.origem.inicio, interno.bloco.origem.fim or 0))

        self._checar_vigencias_conflitantes(blocos, vigencia_base)

        nao_mapeados = self._trechos_nao_mapeados(texto, raw, spans)
        return ResultadoExtracao(blocos, pend_vigencia_base, nao_mapeados, contexto)

    # --------------------------------------------------------------- vigência
    def _vigencia_base(
        self, request: InterpretarRequestV2, raw: InterpretacaoCampanhaRawLLM, contexto: dict[str, Any]
    ) -> tuple[tuple[date | None, date | None], list[Pendencia]]:
        if request.vigenciaCampanha and (request.vigenciaCampanha.inicio or request.vigenciaCampanha.fim):
            return (request.vigenciaCampanha.inicio, request.vigenciaCampanha.fim), []
        if raw.vigencia_inicio_raw or raw.vigencia_fim_raw:
            ini, fim, pend = normalizar_datas(raw.vigencia_inicio_raw, raw.vigencia_fim_raw, contexto)
            return (ini, fim), [pendencia_de_texto(p, "vigencia") for p in pend]
        return (None, None), []

    def _checar_vigencias_conflitantes(
        self, blocos: list[BlocoInterno], base: tuple[date | None, date | None]
    ) -> None:
        """Sem vigência da campanha, períodos citados por regras diferentes entre si são incompatíveis."""
        if base != (None, None):
            return
        periodos = {
            (b.bloco.dataInicio, b.bloco.dataFim)
            for b in blocos
            if (b.bloco.dataInicio, b.bloco.dataFim) != (None, None)
        }
        if len(periodos) > 1:
            for b in blocos:
                if (b.bloco.dataInicio, b.bloco.dataFim) != (None, None):
                    b.bloco.pendencias.append(
                        pendencia(
                            CodigoPendencia.VIGENCIA_INCOMPATIVEL,
                            "As regras citam períodos diferentes; todas devem herdar a vigência comum da campanha.",
                            "vigencia",
                            "Qual é a vigência comum da campanha?",
                        )
                    )

    # ------------------------------------------------------------------ bloco
    def _montar_bloco(
        self,
        id_local: str,
        regra: RegraRawLLM,
        texto: str,
        contexto: dict[str, Any],
        vigencia_base: tuple[date | None, date | None],
    ) -> BlocoInterno:
        pend: list[Pendencia] = []
        pend_txt_norm: list[str] = []  # para confiança

        # origem (anti-alucinação: o trecho precisa existir no pedido)
        origem: Origem | None = None
        loc = localizar_trecho(texto, regra.trecho_origem)
        if loc:
            origem = Origem(trecho=texto[loc[0]:loc[1]], inicio=loc[0], fim=loc[1])
        else:
            pend.append(
                pendencia(
                    CodigoPendencia.TRECHO_INCOMPLETO,
                    "O trecho de origem informado pela IA não foi encontrado no pedido e foi descartado.",
                    "origem",
                )
            )

        # público
        canal, p = normalizar_canal(regra.canal, contexto)
        pend_txt_norm += p
        pend += [pendencia_de_texto(x, "condicoes.canal") for x in p]
        cod_marca, descr_marca, p = normalizar_marca(regra.marca_raw, contexto)
        pend_txt_norm += p
        pend += [pendencia_de_texto(x, "condicoes.codMarca") for x in p]
        cod_loja, p = normalizar_loja(regra.loja_raw)
        pend_txt_norm += p
        pend += [pendencia_de_texto(x, "condicoes.codLoja") for x in p]
        cod_cargo, descri_cargo, p = normalizar_cargo(regra.cargo_raw, contexto)
        pend_txt_norm += p
        pend += [pendencia_de_texto(x, "condicoes.codCargo") for x in p]
        matricula, p = normalizar_matricula(regra.matricula_raw)
        pend_txt_norm += p
        pend += [pendencia(CodigoPendencia.MATRICULA_INVALIDA, x, "condicoes.matricula") for x in p]

        # loja contra catálogo, quando o Spring enviou `lojas`
        lojas = (contexto.get("dicionario_dimensoes") or {}).get("lojas")
        if cod_loja is not None and lojas:
            conhecidas = {str(k) for k in (lojas.keys() if isinstance(lojas, dict) else lojas)}
            if str(cod_loja) not in conhecidas:
                msg = f"Loja {cod_loja} não encontrada no catálogo de lojas."
                pend_txt_norm.append(msg)
                pend.append(pendencia(CodigoPendencia.CADASTRO_INEXISTENTE, msg, "condicoes.codLoja"))
                cod_loja = None

        # lacunas que o agente pode resolver por ferramenta (termo citado, código não resolvido)
        lacunas: set[str] = set()
        if regra.marca_raw and cod_marca is None:
            lacunas.add("marca")
        if regra.loja_raw and cod_loja is None and not any(
            x.campo == "condicoes.codLoja" for x in pend
        ):
            lacunas.add("loja")
        if regra.cargo_raw and (cod_cargo is None or descri_cargo is None):
            lacunas.add("cargo")

        # faixa
        faixa, p = normalizar_faixa(
            regra.faixa_min_raw, regra.faixa_max_raw, regra.faixa_min_inclusivo, regra.faixa_max_inclusivo
        )
        pend_txt_norm += p
        pend += [pendencia(CodigoPendencia.CAMPO_AUSENTE, x, "condicoes.faixaValor") for x in p]

        # taxa / operação (IA-2 só resolve taxa absoluta; ajustes são do IA-5)
        taxa: Decimal | None = None
        operacao: Operacao | None = None
        if regra.operacao_raw and regra.operacao_raw.strip():
            pend.append(
                pendencia(
                    CodigoPendencia.CAMPO_AUSENTE,
                    f"Ajuste sobre a taxa base ('{regra.operacao_raw.strip()}') depende da comissão base; "
                    "a taxa final ainda não foi calculada.",
                    "taxa",
                    "Confirme o público para consultar a base de comissão.",
                )
            )
        elif regra.taxa_raw is not None and regra.taxa_raw.strip():
            taxa, p = normalizar_taxa(regra.taxa_raw)
            pend_txt_norm += p
            pend += [pendencia_de_texto(x, "taxa") for x in p]
            if taxa is not None:
                operacao = Operacao(tipo="TAXA_ABSOLUTA", valor=taxa)
        elif regra.bonus_percentual_raw is None and regra.bonus_valor_raw is None:
            msg = "Taxa/percentual de comissão não identificado no trecho."
            pend_txt_norm.append(msg)
            pend.append(
                pendencia(CodigoPendencia.CAMPO_AUSENTE, msg, "taxa", "Qual é o percentual de comissão desta regra?")
            )

        # bônus
        bonus: Bonus | None = None
        b_pct: Decimal | None = None
        b_val: Decimal | None = None
        if regra.bonus_percentual_raw:
            b_pct, p = normalizar_taxa(regra.bonus_percentual_raw)
            pend += [pendencia(CodigoPendencia.TAXA_INVALIDA, f"Bônus: {x}", "bonus.percentual") for x in p]
        if regra.bonus_valor_raw:
            b_val, p = normalizar_valor_monetario(regra.bonus_valor_raw)
            pend += [pendencia(CodigoPendencia.CAMPO_AUSENTE, f"Bônus: {x}", "bonus.valorFixo") for x in p]
        if b_pct is not None or b_val is not None:
            bonus = Bonus(percentual=b_pct, valorFixo=b_val)

        # não suportados / ambiguidades por regra
        for crit in regra.criterios_nao_suportados:
            pend.append(
                pendencia(
                    CodigoPendencia.CRITERIO_NAO_SUPORTADO,
                    f"Critério não suportado no MVP: {crit}.",
                    "condicoes",
                )
            )
        for amb in regra.ambiguidades_ou_duvidas:
            if amb:
                pend.append(pendencia_de_texto(amb))

        # vigência: herdada da campanha; período específico divergente é sinalizado
        ini, fim = vigencia_base
        if regra.vigencia_inicio_raw or regra.vigencia_fim_raw:
            r_ini, r_fim, p = normalizar_datas(regra.vigencia_inicio_raw, regra.vigencia_fim_raw, contexto)
            pend += [pendencia_de_texto(x, "vigencia") for x in p]
            if (ini, fim) != (None, None):
                if (r_ini, r_fim) != (None, None) and (r_ini, r_fim) != (ini, fim):
                    pend.append(
                        pendencia(
                            CodigoPendencia.VIGENCIA_INCOMPATIVEL,
                            f"O pedido cita para esta regra o período {r_ini} a {r_fim}, diferente da vigência "
                            f"comum da campanha ({ini} a {fim}). Foi mantida a vigência da campanha.",
                            "vigencia",
                            "Todas as regras da campanha usam a mesma vigência. Confirma a vigência comum?",
                        )
                    )
            else:
                ini, fim = r_ini, r_fim
        if ini is None and fim is None and not regra.vigencia_inicio_raw:
            pend.append(
                pendencia(CodigoPendencia.CAMPO_AUSENTE, "Vigência da campanha não identificada.", "vigencia")
            )

        confianca = calcular_confianca(
            taxa=taxa,
            canal=canal,
            data_inicio=ini,
            data_fim=fim,
            criterios_nao_suportados=regra.criterios_nao_suportados,
            ambiguidades=regra.ambiguidades_ou_duvidas,
            pendencias_normalizacao=pend_txt_norm,
            cod_marca=cod_marca,
            cod_cargo=cod_cargo,
            cod_loja=cod_loja,
            tem_escopo_extra=matricula is not None or faixa is not None,
        )
        bloco = BlocoProposta(
            idLocal=id_local,
            condicoes=Condicoes(
                canal=canal,
                codMarca=cod_marca,
                descrMarca=descr_marca,
                codCargo=cod_cargo,
                descriCargo=descri_cargo,
                codLoja=cod_loja,
                matricula=matricula,
                faixaValor=faixa,
            ),
            operacao=operacao,
            taxa=taxa,
            bonus=bonus,
            dataInicio=ini,
            dataFim=fim,
            origem=origem,
            confianca=confianca,
            pendencias=_unicas(pend),
        )
        return BlocoInterno(bloco=bloco, raw=regra, lacunas_cadastro=lacunas)

    # ------------------------------------------------------------- cobertura
    def _trechos_nao_mapeados(
        self, texto: str, raw: InterpretacaoCampanhaRawLLM, spans: list[tuple[int, int]]
    ) -> list[Origem]:
        encontrados: list[Origem] = []
        vistos: set[tuple[int, int]] = set()
        # 1) o que o próprio modelo declarou, validado contra o texto
        for t in raw.trechos_nao_mapeados:
            loc = localizar_trecho(texto, t)
            if loc and loc not in vistos:
                vistos.add(loc)
                encontrados.append(Origem(trecho=texto[loc[0]:loc[1]], inicio=loc[0], fim=loc[1]))
        # 2) cobertura determinística: cláusulas sem sobreposição com nenhuma regra
        marcadores_vigencia = [
            s for s in (raw.vigencia_inicio_raw, raw.vigencia_fim_raw) if s
        ]
        for m in re.finditer(r"[^.;\n]+", texto):
            ini, fim = m.start(), m.end()
            clausula = texto[ini:fim].strip()
            if len(re.findall(r"\w+", clausula)) < 3:
                continue
            if any(a < fim and b > ini for a, b in spans):
                continue
            if any(loc[0] < fim and loc[1] > ini for loc in vistos):
                continue
            norm = _sem_acento(clausula).lower()
            if any(_sem_acento(v).lower() in norm for v in marcadores_vigencia) and len(norm.split()) <= 6:
                continue  # cláusula que é só a vigência comum
            vistos.add((ini, fim))
            encontrados.append(Origem(trecho=clausula, inicio=ini, fim=fim))
        return encontrados


def _unicas(pendencias: list[Pendencia]) -> list[Pendencia]:
    vistas: set[tuple[str, str, str | None]] = set()
    saida: list[Pendencia] = []
    for p in pendencias:
        chave = (p.codigo.value, p.mensagem, p.campo)
        if chave not in vistas:
            vistas.add(chave)
            saida.append(p)
    return saida


def _catalogo_como_dimensoes(catalogo: dict[str, Any]) -> dict[str, Any]:
    """Aceita o catálogo no formato `dicionario_dimensoes` (ou aninhado nele)."""
    if isinstance(catalogo.get("dicionario_dimensoes"), dict):
        return catalogo["dicionario_dimensoes"]
    return {k: v for k, v in catalogo.items() if k in ("marcas", "cargos", "canais", "lojas")}
