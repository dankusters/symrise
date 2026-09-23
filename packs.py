"""Monta um deck PowerPoint por "pack" definido em `ppts/packs.xlsx`
(aba "Planilha1"): cada linha da planilha e um passo (bloco de
indicador normal, Price/Unit ou uma aba "Adicoes de X"), agrupadas por
"Pack Name" - todas as linhas do mesmo pack viram UM .pptx so, na
ordem das linhas da planilha, salvo em `ppts/<Pack Name>.pptx`.

Mesma ideia de `sequencia.py` (STEPS no codigo), so que a sequencia
mora numa planilha em vez de uma lista Python - pensado pra nao
precisar editar codigo pra montar/ajustar um pack, so a planilha.
Colunas da planilha (cabecalho na linha 1):

    Pack Name       agrupa as linhas - todas com o mesmo nome viram
                    UM arquivo, na ordem das linhas
    Região          Total Brazil | Southeast | Midwest | South |
                    North+Northeast | Regions
    Breakdown By    Segment | Manufacturer | Brand | Sub | SKU |
                    Sub-Sku | BodySplash | (Packaging Type/Content) -
                    vazio = Segment (ignorado quando Região=Regions)
    Top N           10 | 20 | 30 (Sub/SKU/Sub-Sku) ou 5 | 6 | 10
                    (Manufacturer) - vazio = 6
    Segment         Total | Female | Male | Children | Unisex
    Manufacturer / Brand / SubBrand / SKU / Sub-Sku
                    "Total" ou o nome exato da planilha fonte
                    (ex.: "Boticário")
    Is Body Splash  Total | Yes | No (so confiavel com Breakdown By
                    em Sub/SKU/Sub-Sku)
    Indicador       Volume | Units (millions) | Revenue |
                    Buyers (millions) | Penetration Rate |
                    Volume per Buyer | Frequency Rate |
                    Average Price per Liter | Price/Unit |
                    Units Added 2024→2025 | Revenue Added 2024→2025

Reusa exatamente as mesmas funcoes que a tela usa pra montar cada
bloco (`app._build_blocks`/`_build_price_unit_rows`/
`_additions_tab_result`), entao os numeros batem por construcao - e as
mesmas travas de combinacao invalida da tela/`sequencia.py` (Segmento
obrigatorio em certas quebras, Embalagem so com Região, Is Body Splash
so com certas quebras): uma linha invalida recusa com o motivo em vez
de gerar um numero errado com cara de certo.

Rodar:
    uv run python packs.py "NNE+Female"
"""

from __future__ import annotations

import argparse
import time

import pandas as pd

import app as dash_app
from app import (
    ADDITIONS_TABS,
    ADDITIONS_YEAR0,
    ADDITIONS_YEAR1,
    BODY_SPLASH_BREAKDOWN_KEY,
    BODY_SPLASH_BREAKDOWNS,
    EMBALAGEM_BREAKDOWNS,
    INDICATORS,
    PRICE_UNIT_TAB_LABEL,
    REGIAO_VIEWS,
    REGIOES_TAB_KEY,
    SEGMENT_REQUIRED_BREAKDOWNS,
    SEGMENTOS,
    _additions_tab_result,
    _build_blocks,
    _build_price_unit_rows,
)
from export_pptx import add_additions_slide, add_chart_slides, add_price_unit_slide, new_presentation
from insights import generate_insight
from translations import translate

_PACKS_PATH = "ppts/packs.xlsx"
_PACKS_SHEET = "Planilha1"

# rotulo em ingles (como vem da planilha packs.xlsx, escrita por quem
# usa a tela) -> valor cru (PT, como o resto do app usa internamente)
_REGIAO_LOOKUP = {translate(cod): cod for cod in REGIAO_VIEWS}
_REGIAO_LOOKUP[REGIOES_TAB_KEY] = REGIOES_TAB_KEY

_SEGMENTO_LOOKUP = {translate(s): s for s in SEGMENTOS}
_SEGMENTO_LOOKUP["Total"] = "Total"

_BODY_SPLASH_LOOKUP = {"Total": "Total", translate("Sim"): "Sim", translate("Não"): "Não"}

# "Breakdown By" nao passa pelo dicionario de traducao (translations.py -
# esses sao os VALUES internos do dropdown "Quebra por", nao rotulos de
# categoria/dimensao vindos da planilha fonte) - mapeamento proprio,
# case-insensitive, aceitando tanto o rotulo cheio da tela quanto a
# abreviacao usada em packs.xlsx (ex.: "Sub" pra Sub-brand)
_BREAKDOWN_LOOKUP = {
    "": "segmento",
    "segment": "segmento",
    "manufacturer": "fabricante",
    "brand": "marca",
    "sub": "submarca",
    "subbrand": "submarca",
    "sub-brand": "submarca",
    "sku": "variante",
    "subsku": "subvariante",
    "sub-sku": "subvariante",
    "bodysplash": BODY_SPLASH_BREAKDOWN_KEY,
    "body splash": BODY_SPLASH_BREAKDOWN_KEY,
    "packagingtype": "embalagem_tipo",
    "packaging (type)": "embalagem_tipo",
    "packagingcontent": "embalagem_conteudo",
    "packaging (content)": "embalagem_conteudo",
}

# "Indicador" cobre 3 familias de slide diferentes (ver _resolve_indicador):
# os 8 blocos normais (INDICATORS), a aba Price/Unit (PRICE_UNIT_TAB_LABEL,
# sem chave em INDICATOR_BLOCKS - um waterfall por categoria) e as abas
# "Adicoes de X" (ADDITIONS_TABS, tab_label ja no formato exportado por
# app.py, com a seta "→")
_INDICATOR_LOOKUP = {cfg["label"]: key for key, cfg in INDICATORS.items()}
_ADDITIONS_LOOKUP = {cfg["tab_label"]: cfg for cfg in ADDITIONS_TABS}


def _clean(value, default="Total") -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    return str(value).strip()


def _lookup(mapping: dict, raw, field: str, where: str):
    key = _clean(raw, default="")
    if key in mapping:
        return mapping[key]
    raise SystemExit(f"{where}: {field} {raw!r} não reconhecido (esperado um de {sorted(mapping)})")


def _resolve_indicador(raw, where: str):
    """(kind, indicador) - kind e 'indicador' (bloco normal, `indicador`
    e a chave em INDICATORS), 'price_unit' (`indicador` None) ou
    'additions' (`indicador` e o dict de ADDITIONS_TABS)."""
    label = _clean(raw, default="")
    if label in _INDICATOR_LOOKUP:
        return "indicador", _INDICATOR_LOOKUP[label]
    if label == PRICE_UNIT_TAB_LABEL:
        return "price_unit", None
    if label in _ADDITIONS_LOOKUP:
        return "additions", _ADDITIONS_LOOKUP[label]
    opcoes = sorted(_INDICATOR_LOOKUP) + [PRICE_UNIT_TAB_LABEL] + sorted(_ADDITIONS_LOOKUP)
    raise SystemExit(f"{where}: Indicador {raw!r} não reconhecido (esperado um de {opcoes})")


def _resolve_row(row_number: int, row: "pd.Series") -> dict:
    """Aplica os lookups/defaults numa linha da planilha e recusa
    combinacoes que a tela nao deixaria montar - mesmas travas de
    `sequencia._validate` (aqui reaplicadas pras 3 familias de slide,
    ja que as regras de Segmento/Embalagem/Body Splash sao sobre
    quebra+filtros, nao sobre qual indicador esta sendo exportado)."""
    where = f"linha {row_number} de {_PACKS_PATH}"

    regiao = _lookup(_REGIAO_LOOKUP, row["Região"], "Região", where)
    breakdown_raw = _clean(row["Breakdown By"], default="")
    quebra = _lookup(_BREAKDOWN_LOOKUP, breakdown_raw.lower(), "Breakdown By", where)
    segmento = _lookup(_SEGMENTO_LOOKUP, row["Segment"], "Segment", where)
    body_splash = _lookup(_BODY_SPLASH_LOOKUP, row["Is Body Splash"], "Is Body Splash", where)
    kind, indicador = _resolve_indicador(row["Indicador"], where)

    top_n_raw = row["Top N"]
    top_n = int(top_n_raw) if not pd.isna(top_n_raw) else 6

    s = dict(
        kind=kind,
        indicador=indicador,
        regiao=regiao,
        quebra=quebra,
        segmento=segmento,
        fabricante=_clean(row["Manufacturer"]),
        marca=_clean(row["Brand"]),
        submarca=_clean(row["SubBrand"]),
        variante=_clean(row["SKU"]),
        subvariante=_clean(row["Sub-Sku"]),
        top_n=top_n,
        body_splash=body_splash,
        fabricante_outros=True,
    )

    is_regioes = s["regiao"] == REGIOES_TAB_KEY
    deep = any(s[k] != "Total" for k in ("submarca", "variante", "subvariante"))
    if is_regioes:
        if deep and s["segmento"] == "Total":
            raise SystemExit(
                f"{where}: filtro em SubBrand/SKU/Sub-Sku na Região 'Regions' exige Segment "
                f"real (nao 'Total') - a classificacao nao existe em Segment='Total'."
            )
    else:
        if s["quebra"] in SEGMENT_REQUIRED_BREAKDOWNS and s["segmento"] == "Total":
            raise SystemExit(
                f"{where}: Breakdown By {breakdown_raw!r} exige Segment real (nao 'Total') - "
                f"a planilha fonte so detalha esse nivel dentro de um segmento."
            )
        if s["quebra"] in EMBALAGEM_BREAKDOWNS and s["segmento"] != "Total":
            raise SystemExit(f"{where}: Breakdown By {breakdown_raw!r} (Packaging) so combina com Segment='Total'.")

    if s["body_splash"] != "Total" and s["quebra"] not in BODY_SPLASH_BREAKDOWNS:
        raise SystemExit(
            f"{where}: Is Body Splash so e confiavel com Breakdown By em "
            f"{list(BODY_SPLASH_BREAKDOWNS)}, veio {breakdown_raw!r}."
        )

    return s


def _step_label(s: dict) -> str:
    if s["kind"] == "indicador":
        indicador_label = INDICATORS[s["indicador"]]["label"]
    elif s["kind"] == "price_unit":
        indicador_label = PRICE_UNIT_TAB_LABEL
    else:
        indicador_label = s["indicador"]["tab_label"]
    return f"{translate(s['regiao'])} / {s['quebra']} / {indicador_label}"


def _add_step_slides(prs, step: dict) -> int:
    """Acrescenta os slides de UM passo (linha da planilha) a `prs`,
    despachando pro builder certo conforme `step['kind']`. Retorna
    quantos slides foram adicionados (pro manifesto - Price/Unit pode
    render varios, um por categoria, ver `_build_price_unit_rows`)."""
    antes = len(prs.slides)

    if step["kind"] == "indicador":
        blocks = _build_blocks(
            step["quebra"], step["regiao"], step["segmento"], step["fabricante"], step["marca"],
            step["submarca"], step["variante"], step["subvariante"], step["top_n"], step["body_splash"],
            fabricante_outros=step["fabricante_outros"],
        )
        b = blocks[step["indicador"]]
        insight = generate_insight(
            dash_app.df, indicator=step["indicador"], dimension=b["dim_col"], categories=b["categories"],
            filters=b["filters"], value_scale=1.0, value_decimals=b["value_decimals"],
            unit_label=b["insight_unit_label"], additive=b["cfg"]["additive"],
            values_override=b["values"], totals_override=b["true_totals"],
        )
        add_chart_slides(
            prs, b["fig"], b["categories"], b["values"], b["cfg"]["additive"],
            b["value_decimals"], b["true_totals"], highlight_text=insight,
        )

    elif step["kind"] == "price_unit":
        rows = _build_price_unit_rows(
            step["quebra"], step["regiao"], step["segmento"], step["fabricante"], step["marca"],
            step["submarca"], step["variante"], step["subvariante"], step["top_n"], step["body_splash"],
            fabricante_outros=step["fabricante_outros"],
        )
        for row in rows:
            add_price_unit_slide(prs, row["fig"], row["insight"])

    else:  # "additions"
        cfg = step["indicador"]
        fig, _table, insight, names, deltas, indicator_cfg = _additions_tab_result(
            cfg, step["quebra"], step["regiao"], step["segmento"], step["fabricante"], step["marca"],
            step["submarca"], step["variante"], step["subvariante"], step["top_n"], step["body_splash"],
            ["incluir"] if step["fabricante_outros"] else [],
        )
        add_additions_slide(
            prs, fig, names, deltas, indicator_cfg["value_decimals"],
            ADDITIONS_YEAR0, ADDITIONS_YEAR1, highlight_text=insight,
        )

    return len(prs.slides) - antes


def build_pack(pack_name: str, packs_path: str = _PACKS_PATH) -> str:
    df = pd.read_excel(packs_path, sheet_name=_PACKS_SHEET)
    df = df[df["Pack Name"].notna()]
    pack_df = df[df["Pack Name"] == pack_name]
    if pack_df.empty:
        disponiveis = sorted(df["Pack Name"].unique())
        raise SystemExit(f"Pack {pack_name!r} não encontrado em {packs_path}. Disponíveis: {disponiveis}")

    # numero da linha na planilha (cabecalho = linha 1, 1a linha de
    # dados = linha 2) - pro erro de validacao apontar onde corrigir
    steps = [_resolve_row(idx + 2, row) for idx, row in pack_df.iterrows()]

    prs = new_presentation()
    manifesto: list[tuple[int, str, int]] = []
    for i, s in enumerate(steps, start=1):
        rotulo = _step_label(s)
        t0 = time.monotonic()
        print(f"[{i}/{len(steps)}] {rotulo} ...", end="", flush=True)
        antes = len(prs.slides)
        n = _add_step_slides(prs, s)
        manifesto.append((antes + 1, rotulo, n))
        print(f" {n} slide(s) ({time.monotonic() - t0:.1f}s)")

    out_path = f"ppts/{pack_name}.pptx"
    prs.save(out_path)

    print(f"\n{len(prs.slides)} slides -> {out_path}\n")
    print("Slides  Passo")
    for num, rotulo, n in manifesto:
        rng = f"{num}" if n <= 1 else f"{num}-{num + n - 1}"
        print(f"{rng:>7}  {rotulo}")

    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pack", help='Nome do pack (coluna "Pack Name" de ppts/packs.xlsx)')
    ap.add_argument("--packs-file", default=_PACKS_PATH, help=f"caminho da planilha de packs (padrão: {_PACKS_PATH})")
    args = ap.parse_args()
    build_pack(args.pack, args.packs_file)


if __name__ == "__main__":
    main()
