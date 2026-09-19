"""
Script utilitário para validação manual da conexão com o LLM e resposta do modelo (Task S1-A04).

O script possui dois modos:

1. Fluxo completo (padrão):
   Executa o InterpretadorRegraService com uma única chamada real ao LLM.

2. Smoke test:
   Executa apenas uma chamada simples ao LLM para validar autenticação,
   conectividade e resposta do provedor.

Nenhum dos modos cria ou utiliza uma rota HTTP da API (Task S1-A08).

Uso:
    python scripts/test_llm_live.py
    python scripts/test_llm_live.py "Comissão de 4% para gerentes na loja 12 em novembro"
    python scripts/test_llm_live.py --smoke
"""

import argparse
import json
import os
import sys

# Garante que a pasta 'src' esteja no PYTHONPATH
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from app.core.config import settings
from app.core.exceptions import (
    LLMAuthenticationError,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponseParsingError,
    LLMTimeoutError,
)
from app.core.prompts.regra_prompt import montar_prompt_interpretacao
from app.core.services.interpretador import InterpretadorRegraService
from app.providers import get_provider
from app.schemas.raw import InterpretacaoRegraRawLLM
from app.schemas.regra import InterpretacaoRegraRequest


CATALOGO_EXEMPLO = {
    "ano_referencia": 2026,
    "dicionario_dimensoes": {
        "marcas": {
            "10": "PRETO",
            "20": "BRANCO",
            "30": "AZUL",
        },
        "cargos": {
            "100": "VENDEDOR LOJA",
            "150": "GERENTE DE LOJA",
            "200": "VENDEDOR BALCAO",
        },
        "canais": [
            "LOJA_FISICA",
            "ECOMMERCE",
            "BALCAO",
            "WHATSAPP",
        ],
    },
}

REGRA_PADRAO = (
    "Comissão de 3.5% para os vendedores da marca PRETO na loja 75 "
    "durante todo o mês de outubro de 2026"
)


def _mascarar_chave(chave: str) -> str:
    """Exibe apenas parte da API key para facilitar diagnóstico sem expor o segredo."""
    if not chave:
        return "[NÃO DEFINIDA]"

    if len(chave) <= 8:
        return "***"

    return f"{chave[:4]}...{chave[-4:]}"


def etapa_smoke_test(provider) -> bool:
    """
    Executa um único request real ao provedor para validar conexão.

    Este modo deve ser utilizado somente quando o objetivo for verificar
    autenticação, conectividade e resposta básica do modelo.
    """
    print("\n" + "=" * 60)
    print("SMOKE TEST / CONEXÃO COM O PROVEDOR")
    print("=" * 60)

    prompt_ping = (
        "Responda somente com JSON no formato "
        '{"status": "ok", "mensagem": "conexão funcionando"}'
    )

    schema_ping = {
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "mensagem": {"type": "string"},
        },
        "required": ["status"],
    }

    try:
        print("Enviando uma única requisição de teste ao modelo...")

        resposta = provider.complete(
            prompt=prompt_ping,
            response_schema=schema_ping,
        )

        print("-> Conexão estabelecida com sucesso!")
        print(
            "-> Resposta do modelo:"
        )
        print(
            json.dumps(
                resposta,
                indent=2,
                ensure_ascii=False,
            )
        )

        return True

    except LLMAuthenticationError as err:
        print(f"\n[ERRO DE AUTENTICAÇÃO]: {err}")
    except LLMRateLimitError as err:
        print(f"\n[ERRO DE RATE LIMIT / QUOTA]: {err}")
    except LLMTimeoutError as err:
        print(f"\n[ERRO DE TIMEOUT]: {err}")
    except LLMProviderError as err:
        print(f"\n[ERRO DO PROVEDOR LLM]: {err}")
    except Exception as err:
        print(f"\n[ERRO NO SMOKE TEST]: {err}")

    return False


def etapa_fluxo_completo(
    service: InterpretadorRegraService,
    texto_regra: str,
) -> None:
    """
    Executa o fluxo completo do InterpretadorRegraService.

    IMPORTANTE:
    Esta função não chama o provider diretamente.
    A única chamada ao LLM acontece internamente no service.interpretar().
    """
    print("\n" + "=" * 60)
    print("FLUXO COMPLETO DO INTERPRETADOR")
    print("=" * 60)

    print(f'\nTexto da regra:\n"{texto_regra}"')

    contexto = CATALOGO_EXEMPLO

    request = InterpretacaoRegraRequest(
        texto=texto_regra,
        contexto=contexto,
    )

    print("\nEnviando uma única requisição ao LLM...")
    print("Aguardando interpretação e normalização...")

    # ÚNICA chamada real ao LLM desta execução.
    response = service.interpretar(request)

    print("\n--- Resposta Final Normalizada ---")

    print(
        json.dumps(
            response.model_dump(mode="json"),
            indent=2,
            ensure_ascii=False,
        )
    )

    print("\n--- Resumo das Validações ---")
    print(f"- Canal:      {response.canal}")
    print(f"- Taxa:       {response.taxa}")
    print(
        f"- Marca:      {response.descrMarca} "
        f"(código: {response.codMarca})"
    )
    print(
        f"- Cargo:      {response.descriCargo} "
        f"(código: {response.codCargo})"
    )
    print(f"- Loja:       {response.codLoja}")
    print(
        f"- Vigência:   {response.dataInicio} "
        f"até {response.dataFim}"
    )
    print(f"- Confiança:  {response.confianca}")
    print(
        f"- Pendências: "
        f"{response.pendencias if response.pendencias else 'Nenhuma'}"
    )


def carregar_argumentos() -> argparse.Namespace:
    """Configura e processa os argumentos da linha de comando."""
    parser = argparse.ArgumentParser(
        description=(
            "Validador manual de conexão e interpretação "
            "de regras com LLM real."
        )
    )

    parser.add_argument(
        "texto",
        nargs="?",
        default=REGRA_PADRAO,
        help=(
            "Texto da regra de negócio para interpretar. "
            "Usa um caso padrão quando omitido."
        ),
    )

    parser.add_argument(
        "--smoke",
        action="store_true",
        help=(
            "Executa somente o smoke test de conexão. "
            "Não executa o fluxo de interpretação."
        ),
    )

    return parser.parse_args()


def validar_configuracao() -> None:
    """Valida configurações mínimas antes de realizar qualquer chamada."""
    print("Configurações carregadas (.env / ambiente):")
    print(f"  Provedor LLM:  {settings.llm_provider}")
    print(
        f"  Modelo:        "
        f"{settings.llm_model or '(padrão do provedor)'}"
    )
    print(
        f"  API Key:       "
        f"{_mascarar_chave(settings.llm_api_key)}"
    )
    print(f"  Temperatura:   {settings.llm_temperature}")
    print(
        f"  Timeout:       "
        f"{settings.llm_timeout_seconds}s"
    )

    if not settings.llm_api_key:
        print(
            "\n[ATENÇÃO] Nenhuma LLM_API_KEY encontrada "
            "no arquivo .env ou variáveis de ambiente!"
        )
        print(
            "Configure a variável no arquivo .env antes de executar."
        )
        print("\nExemplo no .env:")
        print("  LLM_PROVIDER=gemini")
        print("  LLM_API_KEY=sua-chave-aqui")

        sys.exit(1)


def criar_provider():
    """Inicializa o provider configurado."""
    try:
        return get_provider()

    except ModuleNotFoundError as err:
        print(f"\n[ERRO DE DEPENDÊNCIA]: {err}")
        print(
            "O SDK do provedor selecionado precisa ser instalado."
        )
        print("\nExecute:")

        print("  pip install google-genai          # Para Gemini")
        print("  pip install openai                # Para OpenAI")
        print("  pip install anthropic             # Para Anthropic")

        sys.exit(1)

    except LLMAuthenticationError as err:
        print(f"\n[ERRO DE AUTENTICAÇÃO]: {err}")
        sys.exit(1)

    except Exception as err:
        print(
            f"\n[ERRO AO INICIALIZAR PROVEDOR]: {err}"
        )
        sys.exit(1)


def main() -> None:
    args = carregar_argumentos()

    validar_configuracao()

    provider = criar_provider()

    # ---------------------------------------------------------
    # MODO SMOKE TEST
    # ---------------------------------------------------------
    #
    # Faz exatamente uma chamada ao LLM.
    #
    if args.smoke:
        sucesso = etapa_smoke_test(provider)

        if not sucesso:
            sys.exit(1)

        print("\n" + "=" * 60)
        print("SMOKE TEST CONCLUÍDO COM SUCESSO!")
        print("=" * 60)

        return

    # ---------------------------------------------------------
    # MODO FLUXO COMPLETO
    # ---------------------------------------------------------
    #
    # O InterpretadorRegraService é responsável pela chamada
    # ao provider. Não fazemos nenhuma chamada manual antes
    # dele para evitar consumo duplicado da quota.
    #
    service = InterpretadorRegraService(provider=provider)

    try:
        etapa_fluxo_completo(
            service=service,
            texto_regra=args.texto,
        )

    except LLMAuthenticationError as err:
        print(f"\n[ERRO DE AUTENTICAÇÃO]: {err}")
        sys.exit(1)

    except LLMRateLimitError as err:
        print(f"\n[ERRO DE RATE LIMIT / QUOTA]: {err}")
        print(
            "A execução foi interrompida sem novas tentativas."
        )
        sys.exit(1)

    except LLMTimeoutError as err:
        print(f"\n[ERRO DE TIMEOUT]: {err}")
        sys.exit(1)

    except LLMResponseParsingError as err:
        print(
            f"\n[ERRO NO PARSING DA RESPOSTA DO MODELO]: {err}"
        )
        sys.exit(1)

    except LLMProviderError as err:
        print(f"\n[ERRO DO PROVEDOR LLM]: {err}")
        sys.exit(1)

    except Exception as err:
        print(f"\n[ERRO INESPERADO]: {err}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("TESTE CONCLUÍDO COM SUCESSO!")
    print("=" * 60)


if __name__ == "__main__":
    main()