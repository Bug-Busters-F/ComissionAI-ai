"""
Agente interpretador (Sprint 2, IA-4 / BUG-55).

Laço independente de provedor: a cada passo o LLM devolve uma DECISÃO
estruturada; o Python valida, executa a ferramenta e atualiza o estado. Lacunas são
calculadas de forma determinística; o LLM escolhe qual consultar e pode reescrever
termos de busca, nunca conclui dados. A aprovação continua com o usuário.
"""

import logging
import time
from typing import Any, Callable

from pydantic import ValidationError

from app.core.agente.decisao import DecisaoAgente
from app.core.agente.estado import EstadoAgente, Lacuna
from app.core.agente.hooks import Hooks, HooksPadrao
from app.core.agente.limites import Limites, Orcamento
from app.core.exceptions import LLMAuthenticationError, LLMBaseException
from app.core.llm_retry import completar_com_retry
from app.core.normalizers.confianca import calcular_confianca
from app.core.pendencias import pendencia
from app.core.prompts.agente_prompt import montar_prompt_decisao
from app.core.services.campanha import BlocoInterno, ExtratorCampanha, ResultadoExtracao
from app.providers.base import LLMProvider
from app.schemas.proposta import (
    BlocoProposta,
    CodigoPendencia,
    EvidenciaTool,
    InterpretarRequestV2,
    InterpretarResponseV2,
    Pendencia,
)
from app.tools.base import ToolRegistry, ToolResult

logger = logging.getLogger(__name__)

_CODIGOS_DE_PROBLEMA = {
    CodigoPendencia.AMBIGUIDADE_CARGO,
    CodigoPendencia.AMBIGUIDADE_PUBLICO,
    CodigoPendencia.CADASTRO_INEXISTENTE,
    CodigoPendencia.MATRICULA_INVALIDA,
    CodigoPendencia.BASE_AUSENTE,
    CodigoPendencia.TOOL_FALHA,
}

_CAMPO_POR_DIMENSAO = {
    "marca": "condicoes.codMarca",
    "loja": "condicoes.codLoja",
    "cargo": "condicoes.codCargo",
}


class AgenteInterpretador:
    def __init__(
        self,
        provider: LLMProvider,
        tools: ToolRegistry,
        hooks: Hooks | None = None,
        limites: Limites | None = None,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._provider = provider
        self._tools = tools
        self._hooks: Hooks = hooks or HooksPadrao()
        self._limites = limites
        self._relogio = relogio
        self._extrator = ExtratorCampanha(provider)

    # ------------------------------------------------------------------ fluxo
    def executar(self, request: InterpretarRequestV2) -> InterpretarResponseV2:
        orcamento = Orcamento(self._limites, self._relogio)
        extracao = self._extrator.extrair(request)  # 1ª chamada ao LLM; falhas propagam (401/429/504/502)
        orcamento.passos += 1
        blocos = self._hooks.pos_extracao(extracao.blocos, {"request": request})

        ignorar = None
        if request.contexto.origem == "VERSAO_EXISTENTE":
            ignorar = request.contexto.substituiVersao or request.contexto.campanhaId
        estado = EstadoAgente(blocos=blocos, competencia=request.competencia, ignorar_campanha_id=ignorar)
        pendencias_gerais = list(extracao.pendencias_gerais)

        invalidas = 0
        parada: tuple[CodigoPendencia, str] | None = None
        while True:
            # lacunas sem ferramenta registrada não são perseguidas (nem viram falha)
            lacunas = [l for l in estado.lacunas_abertas() if self._tools.obter(l.ferramenta)]
            if not lacunas:
                break
            motivo = orcamento.motivo_parada()
            if motivo:
                parada = (CodigoPendencia.LIMITE_AGENTE_ATINGIDO, f"{motivo} atingido")
                break
            orcamento.passos += 1  # um passo = uma iteração do laço (decisão + consulta)
            decisao = self._decidir(lacunas, estado, orcamento, pendencias_gerais)
            if decisao is None:
                parada = (CodigoPendencia.TOOL_FALHA, "o modelo ficou indisponível")
                break  # LLM indisponível no meio do laço: preserva o apurado
            if decisao == "INVALIDA":
                invalidas += 1
                if invalidas >= 2:
                    pendencias_gerais.append(
                        pendencia(
                            CodigoPendencia.LIMITE_AGENTE_ATINGIDO,
                            "O agente não conseguiu produzir uma consulta válida; "
                            "as lacunas restantes exigem revisão humana.",
                        )
                    )
                    parada = (CodigoPendencia.LIMITE_AGENTE_ATINGIDO, "o agente não produziu uma consulta válida")
                    break
                continue
            if decisao.acao == "FINALIZAR":
                parada = (CodigoPendencia.LIMITE_AGENTE_ATINGIDO, "o agente encerrou a análise antes")
                break
            lacuna, argumentos = self._resolver_lacuna(decisao, lacunas)
            self._executar_consulta(lacuna, argumentos, estado, orcamento)

        # sem pendência, a condição não conferida sumiria e a regra valeria para todo o público
        if parada:
            restantes = [l for l in estado.lacunas_abertas() if self._tools.obter(l.ferramenta)]
            self._registrar_limite(estado, restantes, *parada)

        for b in estado.blocos:
            self._recalcular_confianca(b)
        finais = self._hooks.antes_de_fechar([b.bloco for b in estado.blocos], {"request": request})
        return self._resposta(request, finais, pendencias_gerais, extracao, estado)

    # ---------------------------------------------------------------- decisão
    def _decidir(
        self,
        lacunas: list[Lacuna],
        estado: EstadoAgente,
        orcamento: Orcamento,
        pendencias_gerais: list[Pendencia],
    ) -> DecisaoAgente | str | None:
        """Com uma só lacuna não há o que decidir: usa o padrão determinístico, sem gastar o LLM."""
        if len(lacunas) == 1:
            unica = lacunas[0]
            return DecisaoAgente(
                acao="CONSULTAR", lacunaId=unica.id, ferramenta=unica.ferramenta, justificativa="única lacuna aberta"
            )
        prompt = montar_prompt_decisao(
            lacunas=[
                {"id": l.id, "tipo": l.tipo, "ferramenta": l.ferramenta, "argumentosPadrao": l.argumentos}
                for l in lacunas
            ],
            ferramentas=self._tools.descricoes(),
            historico=[
                {"ferramenta": e.ferramenta, "argumentos": e.argumentos, "status": e.status} for e in estado.trilha
            ],
        )
        schema = DecisaoAgente.model_json_schema()
        try:
            bruto = completar_com_retry(self._provider, prompt, schema)
            decisao = DecisaoAgente.model_validate(bruto)
        except LLMAuthenticationError:
            raise
        except LLMBaseException as exc:
            logger.warning("LLM indisponível durante o laço do agente: %s", exc.message)
            pendencias_gerais.append(
                pendencia(
                    CodigoPendencia.TOOL_FALHA,
                    "O modelo ficou indisponível durante a análise; as consultas restantes não foram feitas.",
                )
            )
            return None
        except ValidationError:
            return "INVALIDA"
        if decisao.acao == "FINALIZAR":
            return decisao
        if self._tools.obter(decisao.ferramenta or "") is None:
            return "INVALIDA"
        if decisao.lacunaId not in {l.id for l in lacunas}:
            return "INVALIDA"
        return decisao

    def _resolver_lacuna(self, decisao: DecisaoAgente, lacunas: list[Lacuna]) -> tuple[Lacuna, dict[str, Any]]:
        lacuna = next(l for l in lacunas if l.id == decisao.lacunaId)
        if decisao.ferramenta != lacuna.ferramenta:
            return lacuna, lacuna.argumentos  # ferramenta incoerente com a lacuna: usa o padrão
        argumentos = lacuna.argumentos
        if decisao.argumentos and lacuna.tipo == "PUBLICO":
            # o LLM só pode reescrever termos das dimensões que a lacuna já cobre
            permitidos = set(lacuna.argumentos)
            reescrita = {
                k: v
                for k, v in decisao.argumentos.items()
                if k in permitidos and isinstance(v, str) and v.strip()
            }
            argumentos = {**lacuna.argumentos, **reescrita}
        return lacuna, argumentos

    # --------------------------------------------------------------- execução
    def _executar_consulta(
        self,
        lacuna: Lacuna,
        argumentos: dict[str, Any],
        estado: EstadoAgente,
        orcamento: Orcamento,
    ) -> None:
        tool = self._tools.obter(lacuna.ferramenta)
        assert tool is not None
        chave = estado.chave_cache(lacuna.ferramenta, argumentos)
        em_cache = chave in estado.cache
        inicio = time.monotonic()
        if em_cache:
            resultado = estado.cache[chave]
        else:
            orcamento.chamadas += 1
            resultado = tool.executar_dict(argumentos)
            estado.cache[chave] = resultado
        duracao = int((time.monotonic() - inicio) * 1000)
        estado.tratadas.add(lacuna.id)

        b = estado.bloco(lacuna.bloco)
        self._aplicar(b, lacuna, resultado)
        b = self._hooks.pos_consulta(b, lacuna.ferramenta, resultado)
        evidencia = EvidenciaTool(
            ferramenta=lacuna.ferramenta,
            argumentos=argumentos,
            status=resultado.status,
            resumo=_resumir(resultado) + (" (reaproveitado)" if em_cache else ""),
            duracaoMs=0 if em_cache else duracao,
            passo=orcamento.passos,
            blocosAfetados=[lacuna.bloco],
        )
        estado.trilha.append(evidencia)
        b.bloco.evidencias.append(evidencia)
        b.bloco.referencias.extend(resultado.referencias)

    # ---------------------------------------------------- aplicação do resultado
    def _aplicar(self, b: BlocoInterno, lacuna: Lacuna, r: ToolResult) -> None:
        bl = b.bloco
        if lacuna.tipo == "PUBLICO":
            self._aplicar_publico(b, r)
        elif lacuna.tipo == "MATRICULA":
            self._aplicar_matricula(b, r)
        elif lacuna.tipo == "BASE":
            if r.status == "SEM_DADOS":
                bl.pendencias.append(
                    pendencia(
                        CodigoPendencia.BASE_AUSENTE,
                        "Não há base de comissão cadastrada para esta marca e cargo na competência; "
                        "o ajuste sobre a base não pode ser calculado.",
                        "taxa",
                        "Informe a taxa final desejada ou cadastre a base da competência.",
                    )
                )
            elif r.status == "FALHA":
                bl.pendencias.append(_pend_falha("a base de comissão", r))
        elif lacuna.tipo == "CONCORRENCIA":
            if r.status == "OK":
                ids = [str(c.get("idRegra")) for c in (r.dados or {}).get("conflitos", [])]
                bl.pendencias.append(
                    pendencia(
                        CodigoPendencia.CONFLITO_REGRA,
                        f"Há regras ativas concorrentes para este público e período (ids: {', '.join(ids)}).",
                        None,
                        "Deseja manter a proposta mesmo com a concorrência?",
                    )
                )
            elif r.status == "FALHA":
                bl.pendencias.append(_pend_falha("as regras concorrentes", r))

    def _aplicar_publico(self, b: BlocoInterno, r: ToolResult) -> None:
        bl = b.bloco
        dims = (r.dados or {}).get("dimensoes", {})
        if r.status == "FALHA" and not dims:
            bl.pendencias.append(_pend_falha("os cadastros", r))
            return
        for dim, info in dims.items():
            campo = _CAMPO_POR_DIMENSAO[dim]
            st = info.get("status")
            if st == "OK":
                item = info["resolvido"]
                if dim == "marca":
                    bl.condicoes.codMarca = item.get("codigo")
                    bl.condicoes.descrMarca = str(item.get("descricao", "")).upper() or None
                elif dim == "loja":
                    bl.condicoes.codLoja = item.get("codigo")
                else:
                    bl.condicoes.codCargo = item.get("codigo")
                    bl.condicoes.descriCargo = str(item.get("descricao", "")).upper() or None
                b.lacunas_cadastro.discard(dim)
                bl.pendencias = [
                    p
                    for p in bl.pendencias
                    if not (
                        p.campo == campo
                        and p.codigo
                        in (
                            CodigoPendencia.AMBIGUIDADE_CARGO,
                            CodigoPendencia.AMBIGUIDADE_PUBLICO,
                            CodigoPendencia.CADASTRO_INEXISTENTE,
                        )
                    )
                ]
            elif st == "AMBIGUO":
                nomes = " ou ".join(f"'{c.get('descricao')}'" for c in info.get("candidatos", []))
                codigo = CodigoPendencia.AMBIGUIDADE_CARGO if dim == "cargo" else CodigoPendencia.AMBIGUIDADE_PUBLICO
                bl.pendencias = [p for p in bl.pendencias if not (p.campo == campo and p.codigo == codigo)]
                bl.pendencias.append(
                    pendencia(
                        codigo,
                        f"'{info.get('termo')}' corresponde a mais de uma opção: {nomes}.",
                        campo,
                        f"A qual {dim} você se refere?",
                    )
                )
            elif st == "SEM_DADOS":
                bl.pendencias = [
                    p
                    for p in bl.pendencias
                    if not (p.campo == campo and p.codigo == CodigoPendencia.CADASTRO_INEXISTENTE)
                ]
                bl.pendencias.append(
                    pendencia(
                        CodigoPendencia.CADASTRO_INEXISTENTE,
                        f"{dim.capitalize()} '{info.get('termo')}' não existe nos cadastros.",
                        campo,
                        f"Confira o {dim} informado.",
                    )
                )
            else:
                bl.pendencias.append(_pend_falha(f"o cadastro de {dim}", r, info.get("erro")))

    def _aplicar_matricula(self, b: BlocoInterno, r: ToolResult) -> None:
        bl = b.bloco
        m = bl.condicoes.matricula
        if r.status == "SEM_DADOS":
            bl.pendencias.append(
                pendencia(
                    CodigoPendencia.MATRICULA_INVALIDA,
                    f"A matrícula {m} não existe no cadastro.",
                    "condicoes.matricula",
                    "Confira a matrícula informada.",
                )
            )
            return
        if r.status == "FALHA":
            bl.pendencias.append(_pend_falha("a matrícula", r))
            return
        dados = r.dados or {}
        divergencias = []
        if bl.condicoes.codLoja is not None and dados.get("codLoja") not in (None, bl.condicoes.codLoja):
            divergencias.append(f"loja {dados.get('codLoja')} (o pedido cita {bl.condicoes.codLoja})")
        if bl.condicoes.codCargo is not None and dados.get("codCargo") not in (None, bl.condicoes.codCargo):
            divergencias.append(f"cargo {dados.get('codCargo')} (o pedido cita {bl.condicoes.codCargo})")
        if divergencias:
            bl.pendencias.append(
                pendencia(
                    CodigoPendencia.AMBIGUIDADE_PUBLICO,
                    f"A matrícula {m} está vinculada a " + " e ".join(divergencias) + ".",
                    "condicoes.matricula",
                    "Qual vínculo deve valer para esta regra?",
                )
            )
        demissao = dados.get("dataDemissao")
        if demissao and bl.dataInicio and str(demissao) < bl.dataInicio.isoformat():
            bl.pendencias.append(
                pendencia(
                    CodigoPendencia.MATRICULA_INVALIDA,
                    f"A matrícula {m} foi desligada em {demissao}, antes do início da vigência.",
                    "condicoes.matricula",
                )
            )

    # -------------------------------------------------------------- fechamento
    def _registrar_limite(
        self, estado: EstadoAgente, lacunas: list[Lacuna], codigo: CodigoPendencia, motivo: str
    ) -> None:
        for l in lacunas:
            termos = ", ".join(f"{k}='{v}'" for k, v in l.argumentos.items() if isinstance(v, (str, int)))
            estado.bloco(l.bloco).bloco.pendencias.append(
                pendencia(
                    codigo,
                    f"A consulta '{l.ferramenta}'" + (f" ({termos})" if termos else "") + f" não foi feita: {motivo}.",
                    None,
                    "Revise manualmente esta informação.",
                )
            )

    def _recalcular_confianca(self, b: BlocoInterno) -> None:
        bl = b.bloco
        problemas = [p.mensagem for p in bl.pendencias if p.codigo in _CODIGOS_DE_PROBLEMA]
        nao_sup = [p.mensagem for p in bl.pendencias if p.codigo == CodigoPendencia.CRITERIO_NAO_SUPORTADO]
        bl.confianca = calcular_confianca(
            taxa=bl.taxa,
            canal=bl.condicoes.canal,
            data_inicio=bl.dataInicio,
            data_fim=bl.dataFim,
            criterios_nao_suportados=nao_sup,
            ambiguidades=[],
            pendencias_normalizacao=problemas,
            cod_marca=bl.condicoes.codMarca,
            cod_cargo=bl.condicoes.codCargo,
            cod_loja=bl.condicoes.codLoja,
            tem_escopo_extra=bl.condicoes.matricula is not None or bl.condicoes.faixaValor is not None,
        )

    def _resposta(
        self,
        request: InterpretarRequestV2,
        blocos: list[BlocoProposta],
        pendencias_gerais: list[Pendencia],
        extracao: ResultadoExtracao,
        estado: EstadoAgente,
    ) -> InterpretarResponseV2:
        if not blocos:
            status = "SEM_PROPOSTA"
        elif any(b.pendencias for b in blocos) or pendencias_gerais or extracao.trechos_nao_mapeados:
            status = "PROPOSTA_COM_PENDENCIAS"
        else:
            status = "PROPOSTA_COMPLETA"
        return InterpretarResponseV2(
            contexto=request.contexto,
            propostas=blocos,
            pendenciasGerais=pendencias_gerais,
            trechosNaoMapeados=extracao.trechos_nao_mapeados,
            trilhaFerramentas=estado.trilha,
            status=status,
        )


def _pend_falha(o_que: str, r: ToolResult, erro: dict | None = None) -> Pendencia:
    tipo = (erro or {}).get("tipo") or (r.erro.tipo if r.erro else "DESCONHECIDO")
    return pendencia(
        CodigoPendencia.TOOL_FALHA,
        f"Não foi possível consultar {o_que} ({tipo}). Nada foi inferido; revise manualmente.",
        None,
        "Tente novamente mais tarde ou informe o dado manualmente.",
    )


def _resumir(r: ToolResult) -> str:
    if r.status == "FALHA":
        return f"FALHA {r.erro.tipo if r.erro else ''}".strip()
    dados = r.dados or {}
    if "dimensoes" in dados:
        partes = []
        for dim, info in dados["dimensoes"].items():
            st = info.get("status")
            if st == "OK":
                partes.append(f"{dim}=OK({info['resolvido'].get('codigo')})")
            elif st == "AMBIGUO":
                partes.append(f"{dim}=AMBIGUO({len(info.get('candidatos', []))} candidatos)")
            else:
                partes.append(f"{dim}={st}")
        return "; ".join(partes)
    if "conflitos" in dados:
        return f"{len(dados['conflitos'])} regra(s) concorrente(s)"
    if "taxa" in dados:
        return f"taxa base {dados['taxa']}"
    return r.status
