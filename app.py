"""App Dash do dashboard Worldpanel: view principal por Regiao (abas),
com filtros cruzaveis (Segmento, Fabricante, Marca, Submarca, Variante) e
um "Quebra por" que escolhe qual dessas dimensoes vira as categorias
empilhadas do grafico - as demais ficam fixas como filtro de valor
unico. Cada view de regiao traz 3 blocos fixos (grafico + highlight):
Volume, Unidades e Valor com Presentes.

Rodar localmente:
    python app.py
"""

from __future__ import annotations

import re

from dash import Dash, Input, Output, State, dcc, html

from charts import YEARS_DEFAULT, alluvial_stack_chart
from etl import build_dataset
from insights import generate_insight

df = build_dataset()

REGIAO_VIEWS = ["T. Brasil", "Sudeste", "C.Oeste", "Sul", "N+NE"]
SEGMENTOS = ["Feminino", "Masculino", "Infantil", "Unisex"]

SEGMENTO_FILTER_OPTIONS = ["Total"] + SEGMENTOS
FABRICANTE_FILTER_OPTIONS = ["Total"] + sorted(df.loc[df["classificacao"] == "Fabricante", "fabricante"].unique())

# so entram fabricantes/marcas com 2+ filhos diretos - com 1 filho so (que
# em geral repete o nome do pai), quebrar por esse nivel nao mostra nada
_marcas_por_fabricante = (
    df.loc[df["classificacao"] == "Marca"].groupby("fabricante")["marca"].unique().apply(sorted)
)
MARCA_BY_FABRICANTE: dict[str, list[str]] = {
    fab: marcas for fab, marcas in _marcas_por_fabricante.items() if len(marcas) >= 2
}

# submarca e variante nao tem coluna propria: o nome fica em "rotulo" e o
# pai (fabricante/marca) permanece fixo nas colunas correspondentes
_submarcas_por_marca = (
    df.loc[df["classificacao"] == "Sub Marca"].groupby("marca")["rotulo"].unique().apply(sorted)
)
SUBMARCA_BY_MARCA: dict[str, list[str]] = {
    marca: subs for marca, subs in _submarcas_por_marca.items() if len(subs) >= 2
}

_variantes_por_marca = (
    df.loc[df["classificacao"] == "Variante"].groupby("marca")["rotulo"].unique().apply(sorted)
)
VARIANTE_BY_MARCA: dict[str, list[str]] = {
    marca: variantes for marca, variantes in _variantes_por_marca.items() if len(variantes) >= 2
}

# indicadores fixos exibidos nas 3 views (ESCOPO.md secao 3, grupo
# cumulativo/empilhavel); metadados usados por alluvial_stack_chart e
# generate_insight
INDICATOR_BLOCKS = ["volume", "unidades", "valor_com_presentes"]
INDICATORS = {
    "volume": dict(label="Volume (lts)", value_scale=1e-6, value_decimals=1, unit_label="milhoes de litros", is_percent=False, additive=True),
    "unidades": dict(label="Unidades (milhoes)", value_scale=1e-6, value_decimals=1, unit_label="milhoes", is_percent=False, additive=True),
    "valor_com_presentes": dict(label="Valor com Presentes (R$)", value_scale=1e-6, value_decimals=0, unit_label="R$ milhoes", is_percent=False, additive=True),
}

_TOP_N = 6

app = Dash(__name__)
app.title = "Worldpanel Dashboard"


def _children_values(indicator, dim_col, base_filters, parent_cod):
    """Retorna {nome: {ano: valor}} dos filhos DIRETOS de `parent_cod` na
    arvore do Cod. (cod == parent_cod + "." + um inteiro), dentro do
    escopo de `base_filters`.

    Usa o Cod. (nao o rotulo de classificacao) pra decidir quem e filho
    de quem: os buckets "Outros X" da planilha sao residuais do NIVEL
    SEGUINTE, nao irmaos do nivel que o nome sugere (ex.: "Outros Marca"
    e o residual de Sub Marca nao rastreadas individualmente dentro de
    uma marca; "Outros Sub Marca" e o residual de Variante dentro de uma
    submarca) - por isso somar por classificacao=="Marca" ou "Fabricante"
    direto contava esses residuais (e ate fabricantes aninhados, como
    "O. U. I" dentro de Boticario) mais de uma vez. Filtrando por Cod.
    cada valor e contado exatamente uma vez, na profundidade certa,
    seja qual for o rotulo de classificacao da linha."""
    subset = df
    for col, val in base_filters.items():
        subset = subset[subset[col] == val]
    pattern = re.compile(rf"^{re.escape(parent_cod)}\.\d+$")
    subset = subset[subset["cod"].str.match(pattern)]
    if subset.empty:
        return {}

    scale = INDICATORS[indicator]["value_scale"]
    return {
        name: {
            yr: float(subset.loc[subset[dim_col] == name, f"{indicator}_{yr}"].sum()) * scale
            for yr in YEARS_DEFAULT
        }
        for name in subset[dim_col].unique()
    }


def discover_top_categories(indicator, dim_col, base_filters, parent_cod, other_label="Outras", top_n=_TOP_N):
    """Top N filhos diretos de `parent_cod` (ultimo ano) + um grupo
    sintetico com o restante, pra barra sempre fechar o total real."""
    if not parent_cod:
        return [], {}
    values_all = _children_values(indicator, dim_col, base_filters, parent_cod)
    if not values_all:
        return [], {}

    last_yr = YEARS_DEFAULT[-1]
    ranked = sorted(values_all, key=lambda n: values_all[n][last_yr], reverse=True)
    top_names = ranked[:top_n]
    values = {name: values_all[name] for name in top_names}
    categories = list(top_names)
    if len(ranked) > top_n:
        values[other_label] = {
            yr: sum(values_all[n][yr] for n in ranked) - sum(values[n][yr] for n in top_names)
            for yr in YEARS_DEFAULT
        }
        categories.append(other_label)
    return categories, values


def _self_cod(regiao_view, segmento_f, classificacao, fabricante=None, marca=None, rotulo=None):
    """Cod. da linha 'auto-total' de uma entidade (ex.: a propria linha
    Marca=Eudora), usado como `parent_cod` pra buscar os filhos dela."""
    subset = df[
        (df["regiao"] == regiao_view) & (df["segmento"] == segmento_f) & (df["classificacao"] == classificacao)
    ]
    if fabricante is not None:
        subset = subset[subset["fabricante"] == fabricante]
    if marca is not None:
        subset = subset[subset["marca"] == marca]
    if rotulo is not None:
        subset = subset[subset["rotulo"] == rotulo]
    return subset["cod"].iloc[0] if not subset.empty else None


def _fabricante_root_cod(regiao_view, segmento_f):
    """Cod. do noh que agrega 'todos os fabricantes' no escopo atual:
    cod '5' ('T. Fabricantes') quando Segmento='Total', ou o cod mais
    raso do ramo '6.x' (o self-total daquele segmento) caso contrario -
    mesma logica de `_segmento_root_values`, um nivel acima."""
    if segmento_f == "Total":
        return "5"
    subset = df[
        (df["regiao"] == regiao_view)
        & (df["segmento"] == segmento_f)
        & (df["classificacao"] == "Total")
        & (df["fabricante"] == "Total")
        & (df["marca"] == "Total")
    ]
    if subset.empty:
        return None
    return subset.loc[subset["cod"].str.count(r"\.").idxmin(), "cod"]


def _scope_filters(fabricante_f, marca_f, submarca_f, variante_f):
    """Filtros de Fabricante/Marca/Submarca/Variante/Classificacao usados
    quando a quebra do grafico e Segmento (isto e, essas dimensoes ficam
    fixas no nivel mais profundo escolhido, e Segmento vira a dimensao
    variavel)."""
    if variante_f and variante_f != "Total":
        return {"classificacao": "Variante", "fabricante": fabricante_f, "marca": marca_f, "rotulo": variante_f}
    if submarca_f and submarca_f != "Total":
        return {"classificacao": "Sub Marca", "fabricante": fabricante_f, "marca": marca_f, "rotulo": submarca_f}
    if marca_f and marca_f != "Total":
        return {"classificacao": "Marca", "fabricante": fabricante_f, "marca": marca_f}
    if fabricante_f and fabricante_f != "Total":
        return {"classificacao": "Fabricante", "fabricante": fabricante_f}
    return {"classificacao": "Total", "fabricante": "Total", "marca": "Total", "cod": "1"}


def _scope_filters(fabricante_f, marca_f, submarca_f, variante_f):
    """Filtros de Fabricante/Marca/Submarca/Variante/Classificacao usados
    quando a quebra do grafico e Segmento (isto e, essas dimensoes ficam
    fixas no nivel mais profundo escolhido, e Segmento vira a dimensao
    variavel)."""
    if variante_f and variante_f != "Total":
        return {"classificacao": "Variante", "fabricante": fabricante_f, "marca": marca_f, "rotulo": variante_f}
    if submarca_f and submarca_f != "Total":
        return {"classificacao": "Sub Marca", "fabricante": fabricante_f, "marca": marca_f, "rotulo": submarca_f}
    if marca_f and marca_f != "Total":
        return {"classificacao": "Marca", "fabricante": fabricante_f, "marca": marca_f}
    if fabricante_f and fabricante_f != "Total":
        return {"classificacao": "Fabricante", "fabricante": fabricante_f}
    return {"classificacao": "Total", "fabricante": "Total", "marca": "Total", "cod": "1"}


def _breadcrumb(regiao_view, fabricante_f, marca_f, submarca_f, variante_f):
    parts = [regiao_view]
    for value in (fabricante_f, marca_f, submarca_f, variante_f):
        if value and value != "Total":
            parts.append(value)
    return " > ".join(parts)


def _segmento_root_values(regiao_view, indicator):
    """Totais de mercado por segmento (Fabricante/Marca em 'Total'): o
    ramo cod '1'/'2.x' so tem 'segmento'='Total'; o valor real por
    segmento mora nos filhos diretos do cod '6' ('T. Segmentacao'):
    '6.1'=Feminino, '6.2'=Masculino etc."""
    base_filters = {"regiao": regiao_view, "classificacao": "Total", "fabricante": "Total", "marca": "Total"}
    values_all = _children_values(indicator, "segmento", base_filters, parent_cod="6")
    zeros = {yr: 0.0 for yr in YEARS_DEFAULT}
    return {seg: values_all.get(seg, zeros) for seg in SEGMENTOS}


def build_selection(breakdown, regiao_view, segmento_f, fabricante_f, marca_f, submarca_f, variante_f, indicator_id):
    """Retorna (categories, dimension, filters, values_override, title)
    para a combinacao atual de quebra/filtros/regiao."""
    crumb = _breadcrumb(regiao_view, fabricante_f, marca_f, submarca_f, variante_f)

    if breakdown == "segmento":
        if fabricante_f == "Total" and marca_f == "Total" and submarca_f == "Total" and variante_f == "Total":
            # sem nenhum fabricante/marca fixo: usa o ramo cod 6.x (ver
            # _segmento_root_values) em vez do filtro generico, que so
            # enxerga 'segmento'='Total' nesse nivel da arvore
            values = _segmento_root_values(regiao_view, indicator_id)
            return SEGMENTOS, "segmento", {}, values, f"{crumb} > Segmentos"
        filters = {"regiao": regiao_view, **_scope_filters(fabricante_f, marca_f, submarca_f, variante_f)}
        return SEGMENTOS, "segmento", filters, None, f"{crumb} > Segmentos"

    if breakdown == "fabricante":
        base_filters = {"regiao": regiao_view, "segmento": segmento_f}
        parent_cod = _fabricante_root_cod(regiao_view, segmento_f)
        categories, values = discover_top_categories(indicator_id, "fabricante", base_filters, parent_cod)
        return categories, "fabricante", base_filters, values, f"{crumb} > Fabricantes (top {_TOP_N})"

    if breakdown == "marca":
        base_filters = {"regiao": regiao_view, "segmento": segmento_f, "fabricante": fabricante_f}
        parent_cod = _self_cod(regiao_view, segmento_f, "Fabricante", fabricante=fabricante_f)
        categories, values = discover_top_categories(indicator_id, "marca", base_filters, parent_cod)
        return categories, "marca", base_filters, values, f"{crumb} > Marcas"

    if breakdown == "submarca":
        base_filters = {"regiao": regiao_view, "segmento": segmento_f, "fabricante": fabricante_f, "marca": marca_f}
        parent_cod = _self_cod(regiao_view, segmento_f, "Marca", fabricante=fabricante_f, marca=marca_f)
        categories, values = discover_top_categories(indicator_id, "rotulo", base_filters, parent_cod)
        return categories, "rotulo", base_filters, values, f"{crumb} > Submarcas"

    # breakdown == "variante"
    base_filters = {"regiao": regiao_view, "segmento": segmento_f, "fabricante": fabricante_f, "marca": marca_f}
    if submarca_f and submarca_f != "Total":
        parent_cod = _self_cod(regiao_view, segmento_f, "Sub Marca", marca=marca_f, rotulo=submarca_f)
    else:
        parent_cod = _self_cod(regiao_view, segmento_f, "Marca", fabricante=fabricante_f, marca=marca_f)
    categories, values = discover_top_categories(indicator_id, "rotulo", base_filters, parent_cod)
    return categories, "rotulo", base_filters, values, f"{crumb} > Variantes"


def _dropdown(id_, options, value, disabled=False):
    return dcc.Dropdown(id=id_, options=[{"label": o, "value": o} for o in options], value=value, clearable=False, disabled=disabled)


def _chart_block(key):
    return html.Div(
        style={"display": "flex", "gap": "20px", "flexWrap": "wrap", "alignItems": "flex-start", "marginBottom": "36px"},
        children=[
            dcc.Graph(
                id=f"graph-{key}",
                config={"responsive": True, "displayModeBar": False},
                style={"flex": "2", "minWidth": "480px"},
            ),
            html.Div(
                style={"flex": "1", "minWidth": "220px", "padding": "228px 8px 0"},
                children=[
                    html.B("Highlights"),
                    html.P(id=f"insight-text-{key}", style={"margin": "4px 0 0", "fontSize": "15.5px", "lineHeight": "1.5", "color": "#333"}),
                ],
            ),
        ],
    )


app.layout = html.Div(
    style={"fontFamily": "'Roboto', -apple-system, Helvetica, Arial, sans-serif", "maxWidth": "1100px", "margin": "0 auto", "padding": "24px"},
    children=[
        html.H2("Worldpanel Dashboard - Symrise"),
        dcc.Tabs(id="regiao-tabs", value=REGIAO_VIEWS[0], children=[dcc.Tab(label=r, value=r) for r in REGIAO_VIEWS]),
        html.Div(
            style={"margin": "16px 0 12px", "maxWidth": "260px"},
            children=[html.Label("Quebra por"), dcc.Dropdown(id="dimension-dropdown", clearable=False)],
        ),
        html.Div(
            style={"display": "flex", "gap": "16px", "marginBottom": "24px", "flexWrap": "wrap"},
            children=[
                html.Div([html.Label("Segmento"), _dropdown("segmento-filter", SEGMENTO_FILTER_OPTIONS, "Total")], style={"flex": "1", "minWidth": "160px"}),
                html.Div([html.Label("Fabricante"), _dropdown("fabricante-filter", FABRICANTE_FILTER_OPTIONS, "Total")], style={"flex": "1", "minWidth": "160px"}),
                html.Div([html.Label("Marca"), _dropdown("marca-filter", ["Total"], "Total", disabled=True)], style={"flex": "1", "minWidth": "160px"}),
                html.Div([html.Label("Submarca"), _dropdown("submarca-filter", ["Total"], "Total", disabled=True)], style={"flex": "1", "minWidth": "160px"}),
                html.Div([html.Label("Variante"), _dropdown("variante-filter", ["Total"], "Total", disabled=True)], style={"flex": "1", "minWidth": "160px"}),
            ],
        ),
        html.Div(children=[_chart_block(key) for key in INDICATOR_BLOCKS]),
    ],
)


@app.callback(
    Output("dimension-dropdown", "options"),
    Output("dimension-dropdown", "value"),
    Input("fabricante-filter", "value"),
    Input("marca-filter", "value"),
    State("dimension-dropdown", "value"),
)
def update_breakdown_options(fabricante_f, marca_f, current_breakdown):
    options = [
        {"label": "Segmento", "value": "segmento"},
        {"label": "Fabricante", "value": "fabricante"},
    ]
    if fabricante_f in MARCA_BY_FABRICANTE:
        options.append({"label": "Marca", "value": "marca"})
    if marca_f in SUBMARCA_BY_MARCA:
        options.append({"label": "Submarca", "value": "submarca"})
    if marca_f in VARIANTE_BY_MARCA:
        options.append({"label": "Variante", "value": "variante"})
    valid_values = {o["value"] for o in options}
    value = current_breakdown if current_breakdown in valid_values else "segmento"
    return options, value


@app.callback(
    Output("marca-filter", "options"),
    Output("marca-filter", "value"),
    Input("fabricante-filter", "value"),
)
def update_marca_options(fabricante_f):
    marcas = MARCA_BY_FABRICANTE.get(fabricante_f, [])
    return [{"label": o, "value": o} for o in (["Total"] + marcas)], "Total"


@app.callback(
    Output("marca-filter", "disabled"),
    Input("dimension-dropdown", "value"),
    Input("fabricante-filter", "value"),
)
def update_marca_disabled(breakdown, fabricante_f):
    return breakdown == "marca" or fabricante_f not in MARCA_BY_FABRICANTE


@app.callback(
    Output("submarca-filter", "options"),
    Output("submarca-filter", "value"),
    Input("marca-filter", "value"),
)
def update_submarca_options(marca_f):
    submarcas = SUBMARCA_BY_MARCA.get(marca_f, [])
    return [{"label": o, "value": o} for o in (["Total"] + submarcas)], "Total"


@app.callback(
    Output("submarca-filter", "disabled"),
    Input("dimension-dropdown", "value"),
    Input("marca-filter", "value"),
)
def update_submarca_disabled(breakdown, marca_f):
    return breakdown == "submarca" or marca_f not in SUBMARCA_BY_MARCA


@app.callback(
    Output("variante-filter", "options"),
    Output("variante-filter", "value"),
    Input("marca-filter", "value"),
)
def update_variante_options(marca_f):
    variantes = VARIANTE_BY_MARCA.get(marca_f, [])
    return [{"label": o, "value": o} for o in (["Total"] + variantes)], "Total"


@app.callback(
    Output("variante-filter", "disabled"),
    Input("dimension-dropdown", "value"),
    Input("marca-filter", "value"),
)
def update_variante_disabled(breakdown, marca_f):
    return breakdown == "variante" or marca_f not in VARIANTE_BY_MARCA


@app.callback(
    Output("segmento-filter", "options"),
    Output("segmento-filter", "value"),
    Input("dimension-dropdown", "value"),
    State("segmento-filter", "value"),
)
def update_segmento_options(breakdown, current_segmento):
    # Submarca/Variante so existem quebradas por segmento real na
    # planilha (nao ha um "Total" agregado nesse nivel) - por isso
    # "Total" some das opcoes quando a quebra e uma dessas duas, e nao um
    # filtro que "nao se cruza" silenciosamente (o que quebrava o grafico)
    if breakdown in ("submarca", "variante"):
        options = SEGMENTOS
    else:
        options = SEGMENTO_FILTER_OPTIONS
    value = current_segmento if current_segmento in options else options[0]
    return [{"label": o, "value": o} for o in options], value


@app.callback(
    Output("segmento-filter", "disabled"),
    Output("fabricante-filter", "disabled"),
    Input("dimension-dropdown", "value"),
)
def update_filters_disabled(breakdown):
    return breakdown == "segmento", breakdown == "fabricante"


@app.callback(
    [Output(f"graph-{key}", "figure") for key in INDICATOR_BLOCKS]
    + [Output(f"insight-text-{key}", "children") for key in INDICATOR_BLOCKS],
    Input("dimension-dropdown", "value"),
    Input("regiao-tabs", "value"),
    Input("segmento-filter", "value"),
    Input("fabricante-filter", "value"),
    Input("marca-filter", "value"),
    Input("submarca-filter", "value"),
    Input("variante-filter", "value"),
)
def update_charts(breakdown, regiao_view, segmento_f, fabricante_f, marca_f, submarca_f, variante_f):
    if not breakdown:
        breakdown = "segmento"

    figs, insights = [], []
    for key in INDICATOR_BLOCKS:
        cfg = INDICATORS[key]
        categories, dim_col, filters, values_override, title = build_selection(
            breakdown, regiao_view, segmento_f, fabricante_f, marca_f, submarca_f, variante_f, key,
        )
        value_scale = 1.0 if values_override is not None else cfg["value_scale"]

        fig = alluvial_stack_chart(
            df=df, indicator=key, dimension=dim_col, categories=categories, filters=filters,
            title=title, subtitle=cfg["label"], values_override=values_override,
            value_scale=value_scale, value_decimals=cfg["value_decimals"], is_percent=cfg["is_percent"],
        )
        fig.update_layout(autosize=True, width=None)

        insight = generate_insight(
            df, indicator=key, dimension=dim_col, categories=categories, filters=filters,
            value_scale=value_scale, value_decimals=cfg["value_decimals"], unit_label=cfg["unit_label"],
            additive=cfg["additive"], values_override=values_override,
        )
        figs.append(fig)
        insights.append(insight)

    return (*figs, *insights)


if __name__ == "__main__":
    app.run(debug=True)
