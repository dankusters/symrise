"""Monta UM deck PowerPoint com uma sequencia de recortes do dashboard,
na ordem de uma narrativa de analise - em vez de baixar um .pptx por
bloco pela tela e juntar na mao.

Cada entrada de `STEPS` e uma combinacao de filtros identica a que voce
montaria clicando no dashboard; o script chama exatamente as mesmas
funcoes que a tela usa (`app._build_blocks` -> `export_pptx`), entao os
numeros sao os mesmos, por construcao.

Rodar:
    uv run python sequencia.py                    # -> analise.pptx
    uv run python sequencia.py -o norte_nordeste.pptx

Depois de gerado, os textos de Highlights podem ser reescritos sem
tocar em graficos/tabelas - ver `highlights.py`.
"""

from __future__ import annotations

import argparse
import sys
import time

import app as dash_app
from app import (
    BODY_SPLASH_BREAKDOWNS,
    BODY_SPLASH_BREAKDOWN_KEY,
    EMBALAGEM_BREAKDOWNS,
    INDICATOR_BLOCKS,
    INDICATORS,
    REGIAO_VIEWS,
    REGIOES_TAB_KEY,
    SEGMENT_REQUIRED_BREAKDOWNS,
    SEGMENTOS,
    _build_blocks,
)
from export_pptx import add_chart_slides, new_presentation
from insights import generate_insight


# ---------------------------------------------------------------------
# A SEQUENCIA. Edite so isto.
#
# Campos de cada passo (todos opcionais menos `indicador`):
#   indicador   um de INDICATOR_BLOCKS (volume, unidades,
#               valor_com_presentes, compradores, penetracao,
#               vol_por_comprador, frequencia, preco_medio_litros)
#   regiao      "T. Brasil" | "Sudeste" | "C.Oeste" | "Sul" | "N+NE"
#               | "Regions" (a aba que quebra o escopo pelas 4 regioes)
#   quebra      segmento | fabricante | marca | submarca | variante |
#               subvariante | bodysplash | embalagem_tipo |
#               embalagem_conteudo        (ignorado quando regiao="Regions")
#   segmento    "Total" | Feminino | Masculino | Infantil | Unisex
#   fabricante / marca / submarca / variante / subvariante   "Total" ou o nome
#   top_n       10 | 20 | 30 para marca/submarca/variante/subvariante;
#               5 | 6 | 10 para fabricante
#   body_splash "Total" | "Sim" | "Nao"   (so com quebra submarca/variante/subvariante)
#   fabricante_outros  True/False - bloco sintetico "Demais Fabricantes"
#   nota        rotulo livre, so pro log e pro manifesto
# ---------------------------------------------------------------------
STEPS: list[dict] = [
    dict(
        nota="1. Peso de cada regiao no Valor com Presente",
        indicador="valor_com_presentes",
        regiao="Regions",
    ),
    dict(
        nota="2. N+NE: Body Splash vs. resto do mercado (Feminino)",
        indicador="valor_com_presentes",
        regiao="N+NE",
        quebra=BODY_SPLASH_BREAKDOWN_KEY,
        segmento="Feminino",
    ),
    dict(
        nota="3. N+NE: marcas (Feminino)",
        indicador="valor_com_presentes",
        regiao="N+NE",
        quebra="marca",
        segmento="Feminino",
        top_n=10,
    ),
    dict(
        nota="4. N+NE: submarcas (Feminino)",
        indicador="valor_com_presentes",
        regiao="N+NE",
        quebra="submarca",
        segmento="Feminino",
        top_n=10,
    ),
]


_DEFAULTS = dict(
    regiao="T. Brasil",
    quebra="segmento",
    segmento="Total",
    fabricante="Total",
    marca="Total",
    submarca="Total",
    variante="Total",
    subvariante="Total",
    top_n=6,
    body_splash="Total",
    fabricante_outros=True,
    nota="",
)

_REGIOES_VALIDAS = REGIAO_VIEWS + [REGIOES_TAB_KEY]


def _validate(i: int, step: dict) -> dict:
    """Aplica os defaults e recusa combinacoes que a UI nao deixaria
    montar. Sem isso um passo invalido nao estoura - ele devolve numero
    errado com cara de certo (ex.: quebra por Marca com Segmento="Total"
    pega totais de fabricante reaproveitados como "marca", ver o
    comentario em `app.update_segmento_and_bodysplash`)."""
    where = f"STEPS[{i}]" + (f" ({step['nota']})" if step.get("nota") else "")

    desconhecidos = set(step) - set(_DEFAULTS) - {"indicador"}
    if desconhecidos:
        raise SystemExit(f"{where}: campo(s) nao reconhecido(s): {sorted(desconhecidos)}")

    s = {**_DEFAULTS, **step}

    if s.get("indicador") not in INDICATOR_BLOCKS:
        raise SystemExit(f"{where}: `indicador` deve ser um de {INDICATOR_BLOCKS}, veio {s.get('indicador')!r}")
    if s["regiao"] not in _REGIOES_VALIDAS:
        raise SystemExit(f"{where}: `regiao` deve ser uma de {_REGIOES_VALIDAS}, veio {s['regiao']!r}")

    is_regioes = s["regiao"] == REGIOES_TAB_KEY
    deep = any(s[k] not in (None, "Total") for k in ("submarca", "variante", "subvariante"))

    if is_regioes:
        # nao ha "quebra por" nessa aba - a quebra e a propria regiao.
        # Segmento so vira obrigatorio quando o FILTRO desce ate
        # Submarca/Variante/Sub Variante.
        if deep and s["segmento"] == "Total":
            raise SystemExit(
                f"{where}: filtro em Submarca/Variante/Sub Variante na aba Regions exige "
                f"`segmento` real (um de {SEGMENTOS}) - a classificacao nao existe em Segmento='Total'."
            )
    else:
        if s["quebra"] in SEGMENT_REQUIRED_BREAKDOWNS and s["segmento"] == "Total":
            raise SystemExit(
                f"{where}: quebra {s['quebra']!r} exige `segmento` real (um de {SEGMENTOS}). "
                f"A planilha so detalha esse nivel dentro de um segmento; com 'Total' os numeros sairiam errados."
            )
        if s["quebra"] in EMBALAGEM_BREAKDOWNS and s["segmento"] != "Total":
            raise SystemExit(
                f"{where}: quebra {s['quebra']!r} (Embalagem) so combina com Regiao - "
                f"`segmento` precisa ficar 'Total', veio {s['segmento']!r}."
            )

    if s["body_splash"] != "Total" and s["quebra"] not in BODY_SPLASH_BREAKDOWNS:
        raise SystemExit(
            f"{where}: o filtro `body_splash` so e confiavel com quebra em {list(BODY_SPLASH_BREAKDOWNS)}, "
            f"veio quebra={s['quebra']!r}."
        )

    return s


def build(steps: list[dict], out_path: str) -> None:
    prs = new_presentation()
    manifesto: list[tuple[int, str]] = []

    resolvidos = [_validate(i, st) for i, st in enumerate(steps)]

    for i, s in enumerate(resolvidos, start=1):
        rotulo = s["nota"] or f"{INDICATORS[s['indicador']]['label']} / {s['regiao']} / {s['quebra']}"
        t0 = time.monotonic()
        print(f"[{i}/{len(resolvidos)}] {rotulo} ...", end="", flush=True)

        blocks = _build_blocks(
            s["quebra"], s["regiao"], s["segmento"], s["fabricante"], s["marca"],
            s["submarca"], s["variante"], s["subvariante"], s["top_n"], s["body_splash"],
            fabricante_outros=s["fabricante_outros"],
        )
        b = blocks[s["indicador"]]

        insight = generate_insight(
            dash_app.df, indicator=s["indicador"], dimension=b["dim_col"], categories=b["categories"],
            filters=b["filters"], value_scale=1.0, value_decimals=b["value_decimals"],
            unit_label=b["insight_unit_label"], additive=b["cfg"]["additive"],
            values_override=b["values"], totals_override=b["true_totals"],
        )

        antes = len(prs.slides)
        add_chart_slides(
            prs, b["fig"], b["categories"], b["values"], b["cfg"]["additive"],
            b["value_decimals"], b["true_totals"], highlight_text=insight,
        )
        # um passo pode render mais de um slide (tabela grande estoura pra
        # slides de continuacao) - o manifesto registra o slide do COMBO,
        # que e o unico com caixa de Highlights
        manifesto.append((antes + 1, rotulo))
        print(f" slide {antes + 1} ({time.monotonic() - t0:.1f}s)")

    prs.save(out_path)

    print(f"\n{len(prs.slides)} slides -> {out_path}\n")
    print("Slide  Passo")
    for num, rotulo in manifesto:
        print(f"{num:>5}  {rotulo}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", default="analise.pptx", help="arquivo de saida (padrao: analise.pptx)")
    args = ap.parse_args()

    if not STEPS:
        sys.exit("STEPS esta vazio - edite a lista no topo de sequencia.py")
    build(STEPS, args.out)


if __name__ == "__main__":
    main()
