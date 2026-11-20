"""
Gera as bases limpas de RH e Vendas (IA-9 / BUG-122).

Uso (a partir da raiz do repositório):
    python scripts/bases_limpas/gerar.py --origem "../Base Dom Rock" --destino data/bases_limpas

Lê a pasta original sem alterá-la e grava em `--destino`:
    rh/RH_<AAAA-MM>.xlsx e vendas/VENDAS_<AAAA-MM>.xlsx  -> prontos para o importador do backend
                                                          (mesma ordem de colunas, cabeçalho na linha 1)
    csv/<mesmo nome>.csv                                 -> mesma informação, para testes e análises
    registro_correcoes.csv                               -> toda remoção, ajuste e pendência, com justificativa
    resumo.json                                          -> contagens por arquivo e hash do conteúdo

Requer openpyxl (não faz parte do serviço; instale com `pip install openpyxl`).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import openpyxl  # noqa: E402

from limpeza import (  # noqa: E402
    LAYOUT_RH,
    LAYOUT_VENDAS,
    Base,
    Correcao,
    Planilha,
    Registro,
    carregar_taxas,
    competencia_do_nome,
    conferir_totais,
    converter_planilha,
    limpar_rh,
    limpar_vendas,
    linhas_saida,
    resumir,
    verificar_cadastros,
)

SEPARADOR_CSV = ";"  # abre direto no Excel em pt-BR


def ler_planilha(caminho: Path) -> Planilha:
    wb = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
    try:
        ws = wb.worksheets[0]
        linhas = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()
    if not linhas:
        raise ValueError(f"{caminho.name}: planilha vazia.")
    dados = [(i + 1, tuple(r)) for i, r in enumerate(linhas) if i > 0 and any(c is not None for c in r)]
    return Planilha(caminho.name, list(linhas[0]), dados)


def localizar(origem: Path) -> tuple[Path, dict[str, Path], dict[str, Path]]:
    taxas = sorted(origem.rglob("BASE_COMMISS*.xlsx"))
    if len(taxas) != 1:
        raise SystemExit(f"Esperado exatamente um BASE_COMMISS*.xlsx em {origem}; encontrados {len(taxas)}.")
    rh: dict[str, Path] = {}
    vendas: dict[str, Path] = {}
    for p in sorted(origem.rglob("*.xlsx")):
        nome = p.name.upper()
        if nome.startswith("~$") or "COMMISS" in nome:
            continue
        alvo = vendas if "VENDAS" in nome else rh if "RH" in nome else None
        if alvo is None:
            continue
        comp = competencia_do_nome(p.name)
        if comp in alvo:
            raise SystemExit(f"Dois arquivos para a mesma competência {comp}: {alvo[comp].name} e {p.name}.")
        alvo[comp] = p
    if set(rh) != set(vendas):
        raise SystemExit(f"Competências sem par RH/Vendas: RH={sorted(rh)} Vendas={sorted(vendas)}.")
    return taxas[0], rh, vendas


def gravar_xlsx(caminho: Path, base: Base) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "BASE"
    ws.append([c.cabecalho for c in base.layout])
    for linha in linhas_saida(base):
        ws.append(linha)
    for j, col in enumerate(base.layout, start=1):
        if col.tipo == "data":
            for (cel,) in ws.iter_rows(min_row=2, min_col=j, max_col=j):
                cel.number_format = "DD/MM/YYYY"
        elif col.tipo == "decimal":
            for (cel,) in ws.iter_rows(min_row=2, min_col=j, max_col=j):
                cel.number_format = "0.00"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    wb.save(caminho)


def _csv_valor(v: Any) -> Any:
    return v.isoformat() if hasattr(v, "isoformat") else v


def gravar_csv(caminho: Path, cabecalho: list[str], linhas: list[list[Any]]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=SEPARADOR_CSV)
        w.writerow(cabecalho)
        for linha in linhas:
            w.writerow(["" if v is None else _csv_valor(v) for v in linha])


def executar(origem: Path, destino: Path) -> dict[str, Any]:
    origem, destino = origem.resolve(), destino.resolve()
    if destino == origem or origem in destino.parents:
        raise SystemExit("O destino não pode ficar dentro da pasta original (os originais são preservados).")

    arq_taxas, arqs_rh, arqs_vendas = localizar(origem)
    registro = Registro()
    taxas = carregar_taxas(ler_planilha(arq_taxas), registro)

    bases_rh: dict[str, Base] = {}
    bases_vendas: dict[str, Base] = {}
    for comp in sorted(arqs_rh):
        bases_rh[comp] = converter_planilha(ler_planilha(arqs_rh[comp]), "RH", LAYOUT_RH, registro, comp)
        bases_vendas[comp] = converter_planilha(
            ler_planilha(arqs_vendas[comp]), "VENDAS", LAYOUT_VENDAS, registro, comp)

    for comp, rh in bases_rh.items():
        limpar_rh(rh, taxas, registro)
    matriculas = {comp: {r["matricula"] for r in rh.registros} for comp, rh in bases_rh.items()}
    for comp, vendas in bases_vendas.items():
        limpar_vendas(vendas, bases_rh[comp], taxas, matriculas, registro)
    verificar_cadastros([*bases_rh.values(), *bases_vendas.values()], registro)

    resumo: dict[str, Any] = {"origem": origem.name, "arquivos": []}
    for comp in sorted(bases_rh):
        for base, pasta, prefixo in ((bases_rh[comp], "rh", "RH"), (bases_vendas[comp], "vendas", "VENDAS")):
            conferir_totais(base, registro)
            nome = f"{prefixo}_{comp}"
            gravar_xlsx(destino / pasta / f"{nome}.xlsx", base)
            gravar_csv(destino / "csv" / f"{nome}.csv", [c.cabecalho for c in base.layout], linhas_saida(base))
            item = resumir(base, registro)
            item["arquivoLimpo"] = f"{pasta}/{nome}.xlsx"
            resumo["arquivos"].append(item)

    gravar_csv(destino / "registro_correcoes.csv", list(Correcao.CAMPOS),
               [c.como_linha() for c in registro.correcoes])
    resumo["totalCorrecoes"] = len(registro.correcoes)
    resumo["pendenciasGerais"] = sorted(
        {c.regra for c in registro.correcoes if c.arquivo == "(todas as bases)"})
    (destino / "resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")
    return resumo


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Gera as bases limpas de RH e Vendas (IA-9).")
    ap.add_argument("--origem", required=True, type=Path, help="Pasta com os arquivos originais da Dom Rock.")
    ap.add_argument("--destino", default=Path("data/bases_limpas"), type=Path)
    args = ap.parse_args(argv)
    resumo = executar(args.origem, args.destino)
    for a in resumo["arquivos"]:
        print(f"{a['arquivo']:<28} lidas={a['linhasLidas']:>5} mantidas={a['linhasMantidas']:>5} "
              f"removidas={a['linhasRemovidas']} pendencias={a['pendencias']}")
    print(f"Correções registradas: {resumo['totalCorrecoes']} -> {args.destino / 'registro_correcoes.csv'}")


if __name__ == "__main__":
    main()
