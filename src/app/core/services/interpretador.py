"""
Serviço orquestrador do fluxo de interpretação de regras em linguagem natural (Task S1-A04).

Fluxo de Execução:
1. Montagem do prompt enriquecido com instruções do MVP, contexto e few-shots.
2. Extração estruturada bruta via LLMProvider utilizando o schema intermediário.
3. Normalização determinística de taxa, canal, vigência e dimensões (marca, loja, cargo).
4. Identificação e consolidação de pendências para critérios não suportados ou dados faltantes.
5. Cálculo determinístico do score de confiança técnica.
6. Retorno do DTO padronizado InterpretacaoRegraResponse.
"""

from typing import Any
from pydantic import ValidationError

from app.core.exceptions import LLMResponseParsingError
from app.core.normalizers.canais import normalizar_canal
from app.core.normalizers.confianca import calcular_confianca
from app.core.normalizers.datas import normalizar_datas
from app.core.normalizers.dimensoes import normalizar_cargo, normalizar_loja, normalizar_marca
from app.core.normalizers.taxa import normalizar_taxa
from app.core.prompts.regra_prompt import montar_prompt_interpretacao
from app.providers import get_provider
from app.providers.base import LLMProvider
from app.schemas.raw import InterpretacaoRegraRawLLM
from app.schemas.regra import InterpretacaoRegraRequest, InterpretacaoRegraResponse


class InterpretadorRegraService:
    """
    Serviço core responsável pela interpretação de regras de comissão.
    """

    def __init__(self, provider: LLMProvider | None = None) -> None:
        self._provider = provider

    @property
    def provider(self) -> LLMProvider:
        """Obtém o provedor injetado ou resolve a instância configurada."""
        if self._provider is None:
            self._provider = get_provider()
        return self._provider

    def interpretar(self, request: InterpretacaoRegraRequest) -> InterpretacaoRegraResponse:
        """
        Executa o pipeline completo de interpretação e normalização de uma regra.

        Args:
            request: Payload com texto do comando e metadados contextuais.

        Returns:
            InterpretacaoRegraResponse com campos normalizados, confiança e pendências.
        """
        texto = request.texto.strip()
        contexto = request.contexto or {}

        # 1. Montagem do prompt especializado
        prompt = montar_prompt_interpretacao(texto=texto, contexto=contexto)

        # 2. Chamada ao provedor com esquema intermediário bruto
        schema = InterpretacaoRegraRawLLM.model_json_schema()
        raw_dict = self.provider.complete(prompt=prompt, response_schema=schema)

        # 3. Validação estrutural dos dados brutos retornados pelo LLM
        try:
            raw_output = InterpretacaoRegraRawLLM.model_validate(raw_dict)
        except ValidationError as exc:
            raise LLMResponseParsingError(
                f"Estrutura bruta inválida retornada pelo LLM: {exc}"
            ) from exc

        # 4. Normalização determinística em Python
        taxa_norm, pend_taxa = normalizar_taxa(raw_output.taxa_raw)
        canal_norm, pend_canal = normalizar_canal(raw_output.canal, contexto)
        dt_inicio_norm, dt_fim_norm, pend_datas = normalizar_datas(
            raw_output.vigencia_inicio_raw,
            raw_output.vigencia_fim_raw,
            contexto,
        )

        # 4b. Normalização das dimensões de negócio (marca, loja, cargo)
        cod_marca, descr_marca, pend_marca = normalizar_marca(raw_output.marca_raw, contexto)
        cod_loja, pend_loja = normalizar_loja(raw_output.loja_raw)
        cod_cargo, descri_cargo, pend_cargo = normalizar_cargo(raw_output.cargo_raw, contexto)

        # 5. Consolidação de pendências e critérios não suportados
        pendencias: list[str] = []

        if raw_output.criterios_nao_suportados:
            criterios_formatados = ", ".join(raw_output.criterios_nao_suportados)
            pendencias.append(
                f"Critério(s) não suportado(s) no MVP identificado(s): {criterios_formatados}."
            )

        if raw_output.ambiguidades_ou_duvidas:
            for amb in raw_output.ambiguidades_ou_duvidas:
                if amb and amb not in pendencias:
                    pendencias.append(amb)

        for pend in pend_canal + pend_taxa + pend_datas + pend_marca + pend_loja + pend_cargo:
            if pend and pend not in pendencias:
                pendencias.append(pend)

        # 6. Cálculo determinístico de confiança
        pendencias_norm = pend_taxa + pend_canal + pend_datas + pend_marca + pend_loja + pend_cargo
        confianca_calculada = calcular_confianca(
            taxa=taxa_norm,
            canal=canal_norm,
            data_inicio=dt_inicio_norm,
            data_fim=dt_fim_norm,
            criterios_nao_suportados=raw_output.criterios_nao_suportados,
            ambiguidades=raw_output.ambiguidades_ou_duvidas,
            pendencias_normalizacao=pendencias_norm,
            cod_marca=cod_marca,
            cod_cargo=cod_cargo,
            cod_loja=cod_loja,
        )

        # 7. Construção do DTO de resposta do contrato
        return InterpretacaoRegraResponse(
            canal=canal_norm,
            codMarca=cod_marca,
            descrMarca=descr_marca,
            codCargo=cod_cargo,
            descriCargo=descri_cargo,
            codLoja=cod_loja,
            taxa=taxa_norm,
            dataInicio=dt_inicio_norm,
            dataFim=dt_fim_norm,
            confianca=confianca_calculada,
            pendencias=pendencias,
        )
