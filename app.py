"""App Dash do dashboard Worldpanel: escolhe indicador + quebra (Regiao,
Segmento, Fabricante ou Marca) e filtros (Regiao/Segmento/Fabricante/
Marca), redesenhando grafico + comentario automatico juntos, a partir
das mesmas funcoes de etl.py, charts.py e insights.py.

Rodar localmente:
    python app.py
"""

from __future__ import annotations

from dash import Dash, Input, Output, State, dcc, html

from charts import YEARS_DEFAULT, alluvial_stack_chart, line_evolution_chart
from etl import build_dataset
from insights import generate_insight

df = build_dataset()

REGIOES = ["N+NE", "Sudeste", "C.Oeste", "Sul"]
SEGMENTOS = ["Feminino", "Masculino", "Infantil", "Unisex"]

REGIAO_FILTER_OPTIONS = ["T. Brasil"] + sorted(v for v in df["regiao"].unique() if v != "T. Brasil")
SEGMENTO_FILTER_OPTIONS = ["Total"] + [s for s in SEGMENTOS]
FABRICANTE_FILTER_OPTIONS = ["Total"] + sorted(df.loc[df["classificacao"] == "Fabricante", "fabricante"].unique())

# so entram fabricantes com 2+ marcas proprias - com 1 marca so (que em
# geral repete o nome do fabricante), quebrar por Marca nao mostra nada
_marcas_por_fabricante = (
    df.loc[df["classificacao"] == "Marca"].groupby("fabricante")["marca"].unique().apply(sorted)
)
MARCA_BY_FABRICANTE: dict[str, list[str]] = {
    fab: marcas for fab, marcas in _marcas_por_fabricante.items() if len(marcas) >= 2
}

SEGMENTO_SHARE_FILTERS = {
    "regiao": "T. Brasil",
    "segmento": "Total",
    "fabricante": "Total",
    "marca": "Total",
    "classificacao": "Total",
}

# indicadores do escopo (ESCOPO.md secao 3): "chart" define qual template
# usar; "is_share" marca os dois indicadores cujo share so faz sentido
# quebrado por Segmento (o Cod. nao tem relacao pai/filho entre regioes
# nem entre fabricantes/marcas na forma como esta modelado hoje)
INDICATORS = {
    "volume": dict(label="Volume (lts)", chart="alluvial", value_scale=1e-6, value_decimals=1, unit_label="milhoes de litros", is_percent=False, additive=True, is_share=False),
    "unidades": dict(label="Unidades (milhoes)", chart="alluvial", value_scale=1e-6, value_decimals=1, unit_label="milhoes", is_percent=False, additive=True, is_share=False),
    "valor_sem_presentes": dict(label="Valor sem Presentes (R$)", chart="alluvial", value_scale=1e-6, value_decimals=0, unit_label="R$ milhoes", is_percent=False, additive=True, is_share=False),
    "valor_com_presentes": dict(label="Valor com Presentes (R$)", chart="alluvial", value_scale=1e-6, value_decimals=0, unit_label="R$ milhoes", is_percent=False, additive=True, is_share=False),
    "compradores": dict(label="Compradores", chart="alluvial", value_scale=1e-6, value_decimals=1, unit_label="milhoes", is_percent=False, additive=True, is_share=False),
    "share_unidades": dict(label="Share Unidades", chart="alluvial", value_scale=1.0, value_decimals=1, unit_label="", is_percent=True, additive=True, is_share=True),
    "share_valor_com_presentes": dict(label="Share Valor com Presentes %", chart="alluvial", value_scale=1.0, value_decimals=1, unit_label="", is_percent=True, additive=True, is_share=True),
    "penetracao": dict(label="Penetracao", chart="line", value_scale=1.0, value_decimals=1, unit_label="%", is_percent=True, additive=False, is_share=False),
    "vol_por_comprador": dict(label="Vol. por Comprador", chart="line", value_scale=1.0, value_decimals=1, unit_label="litros", is_percent=False, additive=False, is_share=False),
    "frequencia": dict(label="Frequencia", chart="line", value_scale=1.0, value_decimals=1, unit_label="ocasioes/ano", is_percent=False, additive=False, is_share=False),
    "preco_medio_litros": dict(label="Preco Medio (Litros)", chart="line", value_scale=1.0, value_decimals=1, unit_label="R$/litro", is_percent=False, additive=False, is_share=False),
    "preco_medio_unidades": dict(label="Preco Medio (Unidades)", chart="line", value_scale=1.0, value_decimals=1, unit_label="R$/unidade", is_percent=False, additive=False, is_share=False),
}

_TOP_N = 6

app = Dash(__name__)
app.title = "Worldpanel Dashboard"


def discover_top_categories(indicator, dim_col, classificacoes, base_filters, other_label, top_n=_TOP_N):
    """Descobre as categorias de maior peso (ultimo ano) para uma quebra
    por Fabricante/Marca e agrupa o restante (incluindo o bucket
    'Outros Fabricante'/'Outros Marca' ja existente na planilha) num
    unico grupo sintetico, para as barras sempre somarem o total real.
    """
    subset = df
    for col, val in base_filters.items():
        subset = subset[subset[col] == val]
    subset = subset[subset["classificacao"].isin(classificacoes)]
    if subset.empty:
        return [], {}

    scale = INDICATORS[indicator]["value_scale"]
    last_col = f"{indicator}_{YEARS_DEFAULT[-1]}"
    sums = subset.groupby(dim_col)[last_col].sum().sort_values(ascending=False)
    top_names = list(sums.index[:top_n])

    values = {
        name: {
            yr: float(subset.loc[subset[dim_col] == name, f"{indicator}_{yr}"].sum()) * scale
            for yr in YEARS_DEFAULT
        }
        for name in top_names
    }
    categories = list(top_names)
    if len(sums) > top_n:
        totals_per_year = {yr: float(subset[f"{indicator}_{yr}"].sum()) * scale for yr in YEARS_DEFAULT}
        values[other_label] = {
            yr: totals_per_year[yr] - sum(values[n][yr] for n in top_names) for yr in YEARS_DEFAULT
        }
        categories.append(other_label)
    return categories, values


def _scope_filters(fabricante_f: str, marca_f: str) -> dict[str, str]:
    """Filtros de Fabricante/Marca/Classificacao usados quando a quebra
    do grafico e Regiao ou Segmento (ou seja, Fabricante/Marca ficam
    fixos, escolhendo o nivel certo da hierarquia do Cod.)."""
    if marca_f and marca_f != "Total":
        return {"classificacao": "Marca", "fabricante": fabricante_f, "marca": marca_f}
    if fabricante_f and fabricante_f != "Total":
        return {"classificacao": "Fabricante", "fabricante": fabricante_f}
    return {"classificacao": "Total", "fabricante": "Total", "marca": "Total", "cod": "1"}


def build_selection(indicator_id, breakdown, regiao_f, segmento_f, fabricante_f, marca_f):
    """Retorna (categories, dimension, filters, values_override, title)
    para a combinacao atual de indicador/quebra/filtros."""
    cfg = INDICATORS[indicator_id]

    if breakdown == "regiao":
        filters = {"segmento": segmento_f, **_scope_filters(fabricante_f, marca_f)}
        return REGIOES, "regiao", filters, None, "Brasil > Todos os segmentos > Regioes"

    if breakdown == "segmento":
        if cfg["is_share"]:
            return SEGMENTOS, "rotulo", SEGMENTO_SHARE_FILTERS, None, "Brasil > T. Brasil > Segmentos"
        filters = {"regiao": regiao_f, **_scope_filters(fabricante_f, marca_f)}
        return SEGMENTOS, "segmento", filters, None, f"{regiao_f} > Segmentos"

    if breakdown == "fabricante":
        base_filters = {"regiao": regiao_f, "segmento": segmento_f}
        categories, values = discover_top_categories(
            indicator_id, "fabricante", ["Fabricante", "Outros Fabricante"], base_filters,
            other_label="Outros Fabricantes",
        )
        return categories, "fabricante", base_filters, values, f"{regiao_f} > Fabricantes (top {_TOP_N})"

    # breakdown == "marca"
    base_filters = {"regiao": regiao_f, "segmento": segmento_f, "fabricante": fabricante_f}
    categories, values = discover_top_categories(
        indicator_id, "marca", ["Marca", "Outros Marca"], base_filters, other_label="Outras",
    )
    return categories, "marca", base_filters, values, f"{regiao_f} > {fabricante_f} > Marcas"


def _dropdown(id_, options, value, disabled=False):
    return dcc.Dropdown(
        id=id_,
        options=[{"label": o, "value": o} for o in options] if options and isinstance(options[0], str) else options,
        value=value,
        clearable=False,
        disabled=disabled,
    )


app.layout = html.Div(
    style={"fontFamily": "'Roboto', -apple-system, Helvetica, Arial, sans-serif", "maxWidth": "1100px", "margin": "0 auto", "padding": "24px"},
    children=[
        html.H2("Worldpanel Dashboard - Symrise"),
        html.Div(
            style={"display": "flex", "gap": "16px", "marginBottom": "12px", "flexWrap": "wrap"},
            children=[
                html.Div([html.Label("Indicador"), dcc.Dropdown(
                    id="indicator-dropdown",
                    options=[{"label": cfg["label"], "value": key} for key, cfg in INDICATORS.items()],
                    value="unidades", clearable=False,
                )], style={"flex": "2", "minWidth": "220px"}),
                html.Div([html.Label("Quebra por"), dcc.Dropdown(id="dimension-dropdown", clearable=False)], style={"flex": "1", "minWidth": "160px"}),
            ],
        ),
        html.Div(
            style={"display": "flex", "gap": "16px", "marginBottom": "16px", "flexWrap": "wrap"},
            children=[
                html.Div([html.Label("Regiao"), _dropdown("regiao-filter", REGIAO_FILTER_OPTIONS, "T. Brasil")], style={"flex": "1", "minWidth": "160px"}),
                html.Div([html.Label("Segmento"), _dropdown("segmento-filter", SEGMENTO_FILTER_OPTIONS, "Total")], style={"flex": "1", "minWidth": "160px"}),
                html.Div([html.Label("Fabricante"), _dropdown("fabricante-filter", FABRICANTE_FILTER_OPTIONS, "Total")], style={"flex": "1", "minWidth": "160px"}),
                html.Div([html.Label("Marca"), _dropdown("marca-filter", ["Total"], "Total", disabled=True)], style={"flex": "1", "minWidth": "160px"}),
            ],
        ),
        html.Div(
            style={"display": "flex", "gap": "20px", "flexWrap": "wrap", "alignItems": "flex-start"},
            children=[
                dcc.Graph(
                    id="graph",
                    config={"responsive": True, "displayModeBar": False},
                    style={"flex": "2", "minWidth": "480px"},
                ),
                html.Div(
                    id="highlights-col",
                    style={"flex": "1", "minWidth": "220px", "padding": "228px 8px 0"},
                    children=[
                        html.B("Highlights"),
                        html.P(id="insight-text", style={"margin": "4px 0 0", "fontSize": "15.5px", "lineHeight": "1.5", "color": "#333"}),
                    ],
                ),
            ],
        ),
    ],
)


@app.callback(
    Output("dimension-dropdown", "options"),
    Output("dimension-dropdown", "value"),
    Input("indicator-dropdown", "value"),
    Input("fabricante-filter", "value"),
    State("dimension-dropdown", "value"),
)
def update_breakdown_options(indicator_id, fabricante_f, current_breakdown):
    if INDICATORS[indicator_id]["is_share"]:
        return [{"label": "Segmento", "value": "segmento"}], "segmento"
    options = [
        {"label": "Regiao", "value": "regiao"},
        {"label": "Segmento", "value": "segmento"},
        {"label": "Fabricante", "value": "fabricante"},
    ]
    if fabricante_f in MARCA_BY_FABRICANTE:
        options.append({"label": "Marca", "value": "marca"})
    valid_values = {o["value"] for o in options}
    value = current_breakdown if current_breakdown in valid_values else "regiao"
    return options, value


@app.callback(
    Output("marca-filter", "options"),
    Output("marca-filter", "value"),
    Output("marca-filter", "disabled"),
    Input("fabricante-filter", "value"),
    Input("dimension-dropdown", "value"),
)
def update_marca_filter(fabricante_f, breakdown):
    marcas = MARCA_BY_FABRICANTE.get(fabricante_f, [])
    options = [{"label": "Total", "value": "Total"}] + [{"label": m, "value": m} for m in marcas]
    disabled = breakdown == "marca" or not marcas
    return options, "Total", disabled


@app.callback(
    Output("regiao-filter", "disabled"),
    Output("segmento-filter", "disabled"),
    Output("fabricante-filter", "disabled"),
    Input("dimension-dropdown", "value"),
    Input("indicator-dropdown", "value"),
)
def update_filters_disabled(breakdown, indicator_id):
    is_share = INDICATORS[indicator_id]["is_share"]
    return (
        breakdown == "regiao" or is_share,
        breakdown == "segmento",
        breakdown == "fabricante" or is_share,
    )


_HIGHLIGHTS_PADDING_TOP = {"alluvial": "228px", "line": "70px"}


@app.callback(
    Output("graph", "figure"),
    Output("insight-text", "children"),
    Output("highlights-col", "style"),
    Input("indicator-dropdown", "value"),
    Input("dimension-dropdown", "value"),
    Input("regiao-filter", "value"),
    Input("segmento-filter", "value"),
    Input("fabricante-filter", "value"),
    Input("marca-filter", "value"),
)
def update_chart(indicator_id, breakdown, regiao_f, segmento_f, fabricante_f, marca_f):
    cfg = INDICATORS[indicator_id]
    if not breakdown:
        breakdown = "segmento" if cfg["is_share"] else "regiao"

    categories, dim_col, filters, values_override, title = build_selection(
        indicator_id, breakdown, regiao_f, segmento_f, fabricante_f, marca_f
    )
    # quando os valores ja vem prontos (Fabricante/Marca com "Outros"),
    # a escala ja foi aplicada em discover_top_categories
    value_scale = 1.0 if values_override is not None else cfg["value_scale"]

    common = dict(
        df=df, indicator=indicator_id, dimension=dim_col, categories=categories,
        filters=filters, title=title, subtitle=cfg["label"], values_override=values_override,
    )
    if cfg["chart"] == "alluvial":
        fig = alluvial_stack_chart(
            value_scale=value_scale, value_decimals=cfg["value_decimals"],
            is_percent=cfg["is_percent"], **common,
        )
    else:
        fig = line_evolution_chart(
            unit_label=cfg["unit_label"], value_decimals=cfg["value_decimals"],
            is_percent=cfg["is_percent"], **common,
        )
    fig.update_layout(autosize=True, width=None)

    insight = generate_insight(
        df,
        indicator=indicator_id,
        dimension=dim_col,
        categories=categories,
        filters=filters,
        value_scale=value_scale,
        value_decimals=cfg["value_decimals"],
        unit_label=cfg["unit_label"],
        additive=cfg["additive"],
        values_override=values_override,
    )
    highlights_style = {
        "flex": "1",
        "minWidth": "220px",
        "padding": f"{_HIGHLIGHTS_PADDING_TOP[cfg['chart']]} 8px 0",
    }
    return fig, insight, highlights_style


if __name__ == "__main__":
    app.run(debug=True)
