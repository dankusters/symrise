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

from charts import YEARS_DEFAULT, alluvial_stack_chart, compute_values, compute_variations, line_evolution_chart
from etl import build_dataset
from insights import generate_insight

df = build_dataset()

REGIAO_VIEWS = ["T. Brasil", "Sudeste", "C.Oeste", "Sul", "N+NE"]
SEGMENTOS = ["Feminino", "Masculino", "Infantil", "Unisex"]

SEGMENTO_FILTER_OPTIONS = ["Total"] + SEGMENTOS
FABRICANTE_FILTER_OPTIONS = ["Total"] + sorted(df.loc[df["classificacao"] == "Fabricante", "fabricante"].unique())

# submarca e variante nao tem coluna propria: o nome fica em "rotulo" e o
# pai (fabricante/marca) permanece fixo nas colunas correspondentes. Sao
# usados so pra popular os dropdowns de filtro em cascata - quebrar por
# Marca/Submarca/Variante funciona mesmo com o pai em "Total" (ver
# _descend_to_level), entao nao ha mais filtro de "2+ itens" aqui
MARCA_BY_FABRICANTE: dict[str, list[str]] = (
    df.loc[df["classificacao"] == "Marca"].groupby("fabricante")["marca"].unique().apply(sorted).to_dict()
)
SUBMARCA_BY_MARCA: dict[str, list[str]] = (
    df.loc[df["classificacao"] == "Sub Marca"].groupby("marca")["rotulo"].unique().apply(sorted).to_dict()
)
VARIANTE_BY_MARCA: dict[str, list[str]] = (
    df.loc[df["classificacao"] == "Variante"].groupby("marca")["rotulo"].unique().apply(sorted).to_dict()
)

# listas completas, usadas quando o filtro pai (Fabricante/Marca) esta em
# "Total" - o dropdown do filho continua oferecendo todo mundo
ALL_MARCAS = sorted(df.loc[df["classificacao"] == "Marca", "marca"].unique())
ALL_SUBMARCAS = sorted(df.loc[df["classificacao"] == "Sub Marca", "rotulo"].unique())
ALL_VARIANTES = sorted(df.loc[df["classificacao"] == "Variante", "rotulo"].unique())

# ordem da cadeia Fabricante > Marca > Sub Marca > Variante, usada pra
# decidir quais filtros ficam habilitados pra cada quebra (Segmento e um
# eixo independente, tratado a parte)
FILTER_DEPTH = {"fabricante": 1, "marca": 2, "submarca": 3, "variante": 4}

# indicadores fixos exibidos nas views (ESCOPO.md secao 3): 3 blocos
# empilhaveis (chart_type="stack", metadados usados por
# alluvial_stack_chart) + os graficos de linha (chart_type="line", nao
# cumulativos - ver line_evolution_chart), que entram um de cada vez.
# "volume" precisa ficar antes de qualquer indicador com `rank_with`
# nesta lista (ver update_charts: as categorias de "rank_with" so estao
# disponiveis apos o bloco correspondente ja ter sido processado).
INDICATOR_BLOCKS = ["volume", "unidades", "valor_com_presentes", "preco_medio_litros"]
INDICATORS = {
    "volume": dict(label="Volume", value_scale=1e-6, value_decimals=1, unit_label="milhões de litros", is_percent=False, additive=True, chart_type="stack"),
    "unidades": dict(label="Unidades (milhões)", value_scale=1e-6, value_decimals=1, unit_label="milhões", is_percent=False, additive=True, chart_type="stack"),
    "valor_com_presentes": dict(label="Valor com Presentes", value_scale=1e-6, value_decimals=0, unit_label="R$ milhões", is_percent=False, additive=True, chart_type="stack"),
    # nao aditivo (preco medio nao se soma entre categorias) - por isso
    # reaproveita o ranking/categorias ja escolhidas no bloco de Volume
    # (`rank_with`) em vez de rankear pelo proprio preco (uma marca de
    # nicho com preco unitario alto poderia "assumir" o topo so por
    # causa do preco); a mesma ponderacao por Volume (`weight_indicator`)
    # tambem da o valor da categoria sintetica "Demais outras"/"Outras"
    # (media ponderada do que sobrou, nunca soma) e a linha tracejada de
    # media ponderada do grafico
    "preco_medio_litros": dict(
        label="Preço Médio (Litros)", value_scale=1.0, value_decimals=1, unit_label="R$/litro",
        is_percent=False, additive=False, chart_type="line", rank_with="volume", weight_indicator="volume",
    ),
}

# indicadores cujo rotulo de unidade alterna entre milhoes/bilhoes
# conforme o total exibido - sem isso, um total grande (ex.: Valor com
# Presentes do mercado inteiro) aparecia como "19031.7 (R$ milhoes)" em
# vez de "19.0 (R$ bilhoes)". Cada entrada: (rotulo em milhoes, rotulo
# em bilhoes, casas decimais quando em bilhoes)
DYNAMIC_UNIT = {
    "volume": ("milhões de litros", "bilhões de litros", 2),
    "valor_com_presentes": ("R$ milhões", "R$ bilhões", 1),
}
_BILLION_THRESHOLD = 1000.0  # valores ja vem em milhoes; 1000 milhoes = 1 bilhao

_TOP_N = 6

# quebras que descobrem categorias dinamicamente (Marca/Submarca/Variante
# podem ter dezenas de itens) ganham um seletor de quantos mostrar,
# sempre rankeados pelo ultimo ano (2025) de cada indicador
TOP_N_BREAKDOWNS = ("marca", "submarca", "variante")
TOP_N_OPTIONS = [10, 20, 30]
TOP_N_DEFAULT = TOP_N_OPTIONS[0]

app = Dash(__name__)
app.title = "Worldpanel Dashboard"


def _scope(base_filters):
    """Aplica `base_filters` (regiao/segmento, tipicamente) uma unica vez
    sobre `df` - usado como ponto de partida tanto por buscas de um nivel
    so quanto pela descida recursiva de `_descend_to_level`, que reusa o
    mesmo subset em vez de refiltrar regiao/segmento a cada passo."""
    subset = df
    for col, val in base_filters.items():
        subset = subset[subset[col] == val]
    return subset


def _cod_children(scoped_df, parent_cod):
    """Linhas filhas DIRETAS de `parent_cod` na arvore do Cod. (cod ==
    parent_cod + "." + um inteiro) dentro de `scoped_df` (ja filtrado por
    regiao/segmento).

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
    pattern = re.compile(rf"^{re.escape(parent_cod)}\.\d+$")
    return scoped_df[scoped_df["cod"].str.match(pattern)]


def _children_rows(base_filters, parent_cod):
    return _cod_children(_scope(base_filters), parent_cod)


def _display_names(frame, dim_col):
    """Serie com o nome de exibicao de cada linha: `dim_col`, exceto
    quando o valor e o literal "Total" - um placeholder de planilha usado
    em linhas agregadoras reais (ex.: "Importados", cujas colunas
    fabricante/marca vem ambas como "Total") que nao e o nome de verdade
    da entidade. Nesses casos usa `rotulo`, que traz o nome correto
    ("Importados-Cf" etc)."""
    return frame[dim_col].where(frame[dim_col] != "Total", frame["rotulo"])


def _children_values(indicator, dim_col, base_filters, parent_cod):
    """{nome: {ano: valor}} dos filhos diretos de `parent_cod` (ver
    `_children_rows`)."""
    subset = _children_rows(base_filters, parent_cod)
    if subset.empty:
        return {}
    scale = INDICATORS[indicator]["value_scale"]
    display = _display_names(subset, dim_col)
    return {
        name: {
            yr: float(subset.loc[display == name, f"{indicator}_{yr}"].sum()) * scale
            for yr in YEARS_DEFAULT
        }
        for name in display.unique()
    }


def _rank_top_n(values_all, other_label="Outras", top_n=_TOP_N, add_other=True):
    """Top N nomes de `values_all` (ultimo ano) + (se `add_other`) um
    grupo sintetico com o restante, pra barra fechar o total real. Com
    `add_other=False` o que sobra do top N e simplesmente descartado do
    grafico (usado quando o "total" exibido nao e mais o real - ver
    `show_total` em `alluvial_stack_chart` - e por isso nao faz sentido
    fechar 100% com um bloco "Outras")."""
    if not values_all:
        return [], {}
    last_yr = YEARS_DEFAULT[-1]
    ranked = sorted(values_all, key=lambda n: values_all[n][last_yr], reverse=True)
    top_names = ranked[:top_n]
    values = {name: values_all[name] for name in top_names}
    categories = list(top_names)
    if add_other and len(ranked) > top_n:
        label = other_label
        if label in values_all:
            # ja existe uma entidade real com esse nome (ex.: "Outras" e
            # tambem um fabricante de verdade, o residual de empresas nao
            # rastreadas documentado no escopo) - o rotulo sintetico do
            # "resto do ranking" precisa de outro nome pra nao sobrescrever
            # nem duplicar essa entidade real na lista de categorias
            label = f"Demais {other_label.lower()}"
        values[label] = {
            yr: sum(values_all[n][yr] for n in ranked) - sum(values[n][yr] for n in top_names)
            for yr in YEARS_DEFAULT
        }
        categories.append(label)
    return categories, values


def _weighted_mean(values_all, weight_all, keys, yr):
    weight_sum = sum(weight_all.get(k, {}).get(yr, 0.0) for k in keys)
    if not weight_sum:
        return 0.0
    return sum(values_all[k][yr] * weight_all.get(k, {}).get(yr, 0.0) for k in keys) / weight_sum


def _apply_ranking(values_all, top_n, other_label="Outras", add_other=True, categories_override=None, weight_all=None):
    """Por padrao (`categories_override=None`), rankeia normalmente (ver
    `_rank_top_n`). Quando `categories_override` e dado - uma lista de
    nomes ja rankeada por OUTRO indicador (ex.: um grafico de Preco
    Medio reaproveitando o ranking de Volume, pra nao deixar uma marca
    de nicho com preco alto "assumir" o topo so por causa do preco) -
    usa exatamente essas categorias/ordem em vez de rankear de novo por
    este indicador. Qualquer categoria da lista que nao seja uma chave
    real de `values_all` (ex.: "Demais outras", o bucket sintetico
    "resto do top N" criado pelo OUTRO indicador) tem seu valor
    recalculado como media ponderada por `weight_all` (tipicamente
    Volume) do que sobrou fora das categorias mostradas - nunca somada,
    pois nao faz sentido somar precos medios/indicadores nao aditivos."""
    if categories_override is None:
        return _rank_top_n(values_all, other_label, top_n, add_other)

    categories = list(categories_override)
    leftover_keys = [k for k in values_all if k not in categories]
    values: dict[str, dict[str, float]] = {}
    for cat in categories:
        if cat in values_all:
            values[cat] = values_all[cat]
        elif weight_all and leftover_keys:
            values[cat] = {yr: _weighted_mean(values_all, weight_all, leftover_keys, yr) for yr in YEARS_DEFAULT}
        else:
            values[cat] = {yr: 0.0 for yr in YEARS_DEFAULT}
    return categories, values


def discover_top_categories(
    indicator, dim_col, base_filters, parent_cod, other_label="Outras", top_n=_TOP_N,
    categories_override=None, weight_indicator=None,
):
    """Top N filhos diretos de `parent_cod` (ultimo ano) + um grupo
    sintetico com o restante, pra barra sempre fechar o total real."""
    if not parent_cod:
        return [], {}
    values_all = _children_values(indicator, dim_col, base_filters, parent_cod)
    weight_all = _children_values(weight_indicator, dim_col, base_filters, parent_cod) if weight_indicator else None
    return _apply_ranking(values_all, top_n, other_label, categories_override=categories_override, weight_all=weight_all)


def _descend_scoped(scale, dim_col, scoped_df, start_cod, target_classificacoes, exclude_classificacoes, year_cols, result, add):
    rows = _cod_children(scoped_df, start_cod)
    if rows.empty:
        return False
    if exclude_classificacoes:
        rows = rows[~rows["classificacao"].isin(exclude_classificacoes)]
        if rows.empty:
            return True  # existiam filhos, so que todos excluidos - nao e uma folha "sem dados"

    at_target = rows["classificacao"].isin(target_classificacoes)
    direct = rows[at_target]
    if not direct.empty:
        grouped = direct.assign(_disp=_display_names(direct, dim_col)).groupby("_disp")[year_cols].sum()
        for name, row_sum in zip(grouped.index, grouped.itertuples(index=False)):
            for yr, value in zip(YEARS_DEFAULT, row_sum):
                add(name, yr, float(value) * scale)

    for row in rows[~at_target].itertuples():
        found = _descend_scoped(scale, dim_col, scoped_df, row.cod, target_classificacoes, exclude_classificacoes, year_cols, result, add)
        if not found:
            # folha antes de chegar no nivel alvo (a planilha nao detalha
            # mais fundo aqui) - a propria linha e o que ha pra mostrar
            name = getattr(row, dim_col)
            if name == "Total":
                name = getattr(row, "rotulo")
            for yr, col in zip(YEARS_DEFAULT, year_cols):
                add(name, yr, float(getattr(row, col)) * scale)

    return True


def _descend_to_level(indicator, dim_col, base_filters, start_cod, target_classificacoes, exclude_classificacoes=frozenset()):
    """{nome: {ano: valor}} de todas as entidades no "nivel alvo" (ex.:
    {"Marca"}, {"Sub Marca"} ou {"Variante"}) descendentes de `start_cod`,
    descendo recursivamente enquanto um filho ainda nao chegou la.

    A arvore nao tem profundidade fixa por nivel: um fabricante com uma
    unica marca pula direto pra Variante (ex.: P&G), uma marca sem
    submarca tambem pula um nivel, e uma linha "folha" (sem filhos, ex.:
    uma submarca cuja planilha nao detalha variantes) conta por si mesma
    - por isso a descida e recursiva e generica, em vez de um numero fixo
    de niveis por quebra. `base_filters` (regiao/segmento) e aplicado uma
    unica vez antes da recursao, que so refaz o match do Cod. a cada
    passo - sem isso, uma descida sem fabricante/marca fixo (arvore
    inteira) refiltrava o dataframe inteiro centenas de vezes.

    `exclude_classificacoes` descarta uma subarvore inteira (nem conta
    como entrada propria, nem desce nela) - usado pra tirar "Outros
    Fabricante" da quebra de Submarca/Variante: e um residual de
    empresas nao rastreadas, nao uma submarca/variante de verdade."""
    if not start_cod:
        return {}
    scoped_df = _scope(base_filters)
    scale = INDICATORS[indicator]["value_scale"]
    year_cols = [f"{indicator}_{yr}" for yr in YEARS_DEFAULT]
    result: dict[str, dict[str, float]] = {}

    def _add(name, yr, value):
        result.setdefault(name, {y: 0.0 for y in YEARS_DEFAULT})[yr] += value

    _descend_scoped(scale, dim_col, scoped_df, start_cod, target_classificacoes, exclude_classificacoes, year_cols, result, _add)
    return result


def _cod_own_values(indicator, cod, base_filters):
    """{ano: valor} da propria linha de `cod` (nao dos filhos) - usado
    como o total "de verdade" (mercado/marca inteiro) quando a quebra
    exibida e so um recorte top N, cujo somatorio nao fecha o total real."""
    if not cod:
        return None
    scoped_df = _scope(base_filters)
    row = scoped_df[scoped_df["cod"] == cod]
    if row.empty:
        return None
    scale = INDICATORS[indicator]["value_scale"]
    row = row.iloc[0]
    return {yr: float(row[f"{indicator}_{yr}"]) * scale for yr in YEARS_DEFAULT}


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


def _resolve_unit(key, values, categories, true_totals=None, years=YEARS_DEFAULT):
    """Se `key` tiver unidade dinamica (ver DYNAMIC_UNIT) e o maior total
    passar de 1 bilhao, reescala `values` (e `true_totals`, se dado) pra
    bilhoes e retorna o rotulo/casas decimais certos; senao devolve os
    valores como vieram (ja em milhoes). Usa `true_totals` (o total real,
    quando o grafico so mostra um top N) pra decidir a unidade quando
    disponivel - a soma das categorias exibidas seria menor que o
    mercado/marca inteiro."""
    if key not in DYNAMIC_UNIT:
        return values, true_totals, None, None
    unit_millions, unit_billions, decimals_billions = DYNAMIC_UNIT[key]
    if true_totals is not None:
        max_total = max(true_totals.values(), default=0.0)
    elif categories:
        max_total = max((sum(values[cat][yr] for cat in categories) for yr in years), default=0.0)
    else:
        return values, true_totals, unit_millions, None
    if max_total >= _BILLION_THRESHOLD:
        rescaled = {cat: {yr: v / 1000.0 for yr, v in yearly.items()} for cat, yearly in values.items()}
        rescaled_totals = (
            {yr: v / 1000.0 for yr, v in true_totals.items()} if true_totals is not None else None
        )
        return rescaled, rescaled_totals, unit_billions, decimals_billions
    return values, true_totals, unit_millions, None


# classificacao excluida da descida de Submarca/Variante: "Outros
# Fabricante" e o residual de empresas nao rastreadas (nunca uma
# submarca/variante de verdade), entao nao concorre por uma vaga no
# ranking nem aparece como "folha" generica quando nao tem detalhe
_EXCLUDE_FROM_RANKING = frozenset({"Outros Fabricante"})


def build_selection(
    breakdown, regiao_view, segmento_f, fabricante_f, marca_f, submarca_f, variante_f, indicator_id, top_n=_TOP_N,
    categories_override=None, weight_indicator=None,
):
    """Retorna (categories, dimension, filters, values_override, title,
    true_totals) para a combinacao atual de quebra/filtros/regiao.
    `true_totals` e None exceto em Submarca/Variante, onde e o total real
    (mercado/marca inteiro) usado pra calcular participacao (MS) - o
    grafico so mostra um top N ali, entao a soma das categorias exibidas
    nao e mais o total de verdade. `categories_override`/`weight_indicator`:
    ver `_apply_ranking` - usado por indicadores nao aditivos (ex.: Preco
    Medio) que reaproveitam o ranking de outro indicador em vez de
    rankear por si mesmos."""
    crumb = _breadcrumb(regiao_view, fabricante_f, marca_f, submarca_f, variante_f)

    if breakdown == "segmento":
        if fabricante_f == "Total" and marca_f == "Total" and submarca_f == "Total" and variante_f == "Total":
            # sem nenhum fabricante/marca fixo: usa o ramo cod 6.x (ver
            # _segmento_root_values) em vez do filtro generico, que so
            # enxerga 'segmento'='Total' nesse nivel da arvore
            values = _segmento_root_values(regiao_view, indicator_id)
            return SEGMENTOS, "segmento", {}, values, f"{crumb} > Segmentos", None
        filters = {"regiao": regiao_view, **_scope_filters(fabricante_f, marca_f, submarca_f, variante_f)}
        return SEGMENTOS, "segmento", filters, None, f"{crumb} > Segmentos", None

    if breakdown == "fabricante":
        base_filters = {"regiao": regiao_view, "segmento": segmento_f}
        parent_cod = _fabricante_root_cod(regiao_view, segmento_f)
        categories, values = discover_top_categories(
            indicator_id, "fabricante", base_filters, parent_cod,
            categories_override=categories_override, weight_indicator=weight_indicator,
        )
        return categories, "fabricante", base_filters, values, f"{crumb} > Fabricantes (top {_TOP_N})", None

    # Marca/Submarca/Variante: nao exigem fabricante/marca/submarca fixo -
    # com o pai em "Total", descobre a partir da raiz (todos os
    # fabricantes) e desce ate o nivel pedido (ver _descend_to_level)
    base_filters = {"regiao": regiao_view, "segmento": segmento_f}

    if breakdown == "marca":
        if fabricante_f and fabricante_f != "Total":
            start_cod = _self_cod(regiao_view, segmento_f, "Fabricante", fabricante=fabricante_f)
        else:
            start_cod = _fabricante_root_cod(regiao_view, segmento_f)
        values_all = _descend_to_level(indicator_id, "marca", base_filters, start_cod, {"Marca"})
        weight_all = _descend_to_level(weight_indicator, "marca", base_filters, start_cod, {"Marca"}) if weight_indicator else None
        categories, values = _apply_ranking(values_all, top_n, categories_override=categories_override, weight_all=weight_all)
        return categories, "marca", base_filters, values, f"{crumb} > Marcas (top {top_n})", None

    if breakdown == "submarca":
        if marca_f and marca_f != "Total":
            start_cod = _self_cod(regiao_view, segmento_f, "Marca", fabricante=fabricante_f, marca=marca_f)
        elif fabricante_f and fabricante_f != "Total":
            start_cod = _self_cod(regiao_view, segmento_f, "Fabricante", fabricante=fabricante_f)
        else:
            start_cod = _fabricante_root_cod(regiao_view, segmento_f)
        values_all = _descend_to_level(indicator_id, "rotulo", base_filters, start_cod, {"Sub Marca"}, _EXCLUDE_FROM_RANKING)
        weight_all = (
            _descend_to_level(weight_indicator, "rotulo", base_filters, start_cod, {"Sub Marca"}, _EXCLUDE_FROM_RANKING)
            if weight_indicator else None
        )
        categories, values = _apply_ranking(
            values_all, top_n, add_other=False, categories_override=categories_override, weight_all=weight_all,
        )
        true_totals = _cod_own_values(indicator_id, start_cod, base_filters)
        return categories, "rotulo", base_filters, values, f"{crumb} > Submarcas (top {top_n})", true_totals

    # breakdown == "variante"
    if submarca_f and submarca_f != "Total":
        start_cod = _self_cod(regiao_view, segmento_f, "Sub Marca", marca=marca_f, rotulo=submarca_f)
    elif marca_f and marca_f != "Total":
        start_cod = _self_cod(regiao_view, segmento_f, "Marca", fabricante=fabricante_f, marca=marca_f)
    elif fabricante_f and fabricante_f != "Total":
        start_cod = _self_cod(regiao_view, segmento_f, "Fabricante", fabricante=fabricante_f)
    else:
        start_cod = _fabricante_root_cod(regiao_view, segmento_f)
    values_all = _descend_to_level(indicator_id, "rotulo", base_filters, start_cod, {"Variante"}, _EXCLUDE_FROM_RANKING)
    weight_all = (
        _descend_to_level(weight_indicator, "rotulo", base_filters, start_cod, {"Variante"}, _EXCLUDE_FROM_RANKING)
        if weight_indicator else None
    )
    categories, values = _apply_ranking(
        values_all, top_n, add_other=False, categories_override=categories_override, weight_all=weight_all,
    )
    true_totals = _cod_own_values(indicator_id, start_cod, base_filters)
    return categories, "rotulo", base_filters, values, f"{crumb} > Variantes (top {top_n})", true_totals


def _dropdown(id_, options, value, disabled=False):
    return dcc.Dropdown(id=id_, options=[{"label": o, "value": o} for o in options], value=value, clearable=False, disabled=disabled)


_POSITIVE_COLOR = "#1E8E5A"
_NEGATIVE_COLOR = "#C23B3B"

_TABLE_CELL_STYLE = {"padding": "3px 6px", "textAlign": "left", "borderBottom": "1px solid #eee", "whiteSpace": "nowrap"}

# largura fixa so do icone (a seta), nao do bloco inteiro - um bloco
# com largura fixa pra "icone+valor" transbordava (sobrepondo a celula
# vizinha) quando o numero era mais largo (ex.: "+146.9%"); deixando so
# o icone com largura fixa e o valor cresce livre ao lado, sem cortar
# nem sobrepor nada, e a seta ainda fica na mesma posicao em toda linha
_ICON_WIDTH = "11px"

# largura MINIMA (nao fixa) do bloco icone+valor - da pra alinhar o
# parenteses do valor nominal numa coluna sem repetir o bug de antes: um
# valor raro maior que isso (ex.: "+298.9%") so empurra o parenteses
# daquela linha, sem cortar nem sobrepor nada
_VALUE_MIN_WIDTH = "60px"

_NOMINAL_COLOR = "#333"


def _variation_span(value, suffix, nominal_text):
    """`value` (variacao, colorida/com seta) seguido do valor nominal
    entre parenteses, em preto (ex.: "+5.3% (77.4)")."""
    nominal_span = html.Span(f"({nominal_text})", style={"color": _NOMINAL_COLOR, "marginLeft": "4px"}) if nominal_text is not None else None
    if value is None:
        value_block = html.Div("–", style={"color": "#aaa", "minWidth": _VALUE_MIN_WIDTH})
    else:
        color = _POSITIVE_COLOR if value >= 0 else _NEGATIVE_COLOR
        icon = "▲" if value >= 0 else "▼"
        value_block = html.Div(
            [
                html.Span(icon, style={"display": "inline-block", "width": _ICON_WIDTH, "color": color}),
                html.Span(f"{value:+.1f}{suffix}", style={"fontVariantNumeric": "tabular-nums", "color": color}),
            ],
            style={"display": "flex", "minWidth": _VALUE_MIN_WIDTH},
        )
    children = [value_block]
    if nominal_span is not None:
        children.append(nominal_span)
    return html.Div(children, style={"display": "flex"})


def _variation_cell(pct, share_pp, nominal, share_value, value_decimals, show_share=True):
    nominal_text = f"{nominal:,.{value_decimals}f}" if nominal is not None else None
    share_text = f"{share_value:.1f}%" if share_value is not None else None
    children = [_variation_span(pct, "%", nominal_text)]
    # indicadores nao aditivos (ex.: Preco Medio) nao tem participacao de
    # mercado - a linha de MS ficaria sempre vazia ("-"), so ruido
    if show_share:
        children.append(html.Div(_variation_span(share_pp, "pp", share_text), style={"marginTop": "2px"}))
    return html.Td(html.Div(children), style=_TABLE_CELL_STYLE)


def _variation_table(categories, values, additive, value_decimals, totals_override=None):
    """Tabela com a variacao % (valor) e a variacao de participacao (MS,
    em pontos percentuais) de cada categoria, ano a ano, cada uma
    seguida do proprio valor nominal entre parenteses (em preto) -
    substitui os rotulos de variacao que antes ficavam dentro do
    grafico. `totals_override`: ver `charts.compute_variations`."""
    if not categories:
        return html.P("Sem dados para esta combinação de filtros.", style={"color": "#888", "fontSize": "12px"})

    variations = compute_variations(values, categories, YEARS_DEFAULT, additive, totals_override)
    year_pairs = [(YEARS_DEFAULT[i][1:], YEARS_DEFAULT[i + 1][1:]) for i in range(len(YEARS_DEFAULT) - 1)]

    header = html.Tr(
        [html.Th("Categoria", style={**_TABLE_CELL_STYLE, "textAlign": "left"})]
        + [html.Th(f"{y0}→{y1}", style=_TABLE_CELL_STYLE) for y0, y1 in year_pairs]
    )
    rows = [
        html.Tr(
            [html.Td(cat, style={**_TABLE_CELL_STYLE, "textAlign": "left", "fontWeight": "600", "whiteSpace": "normal"})]
            + [
                _variation_cell(
                    variations[cat]["pct"][i], variations[cat]["share_pp"][i],
                    variations[cat]["nominal"][i], variations[cat]["share_value"][i],
                    value_decimals, show_share=additive,
                )
                for i in range(len(year_pairs))
            ]
        )
        for cat in categories
    ]
    return html.Table(
        [html.Thead(header), html.Tbody(rows)],
        style={"borderCollapse": "collapse", "width": "100%", "fontSize": "14px"},
    )


def _chart_block(key):
    return html.Div(
        style={"marginBottom": "40px"},
        children=[
            html.Div(
                style={"display": "flex", "gap": "20px", "flexWrap": "wrap", "alignItems": "flex-start"},
                children=[
                    dcc.Graph(
                        id=f"graph-{key}",
                        config={"responsive": True, "displayModeBar": False},
                        style={"flex": "5", "minWidth": "420px"},
                    ),
                    html.Div(id=f"variation-table-{key}", style={"flex": "4", "minWidth": "420px", "paddingTop": "60px"}),
                ],
            ),
            html.Div(
                style={"marginTop": "12px"},
                children=[
                    html.B("Highlights"),
                    html.P(id=f"insight-text-{key}", style={"margin": "4px 0 0", "fontSize": "15.5px", "lineHeight": "1.5", "color": "#333"}),
                ],
            ),
        ],
    )


app.layout = html.Div(
    style={"fontFamily": "'Roboto', -apple-system, Helvetica, Arial, sans-serif", "maxWidth": "1400px", "margin": "0 auto", "padding": "24px"},
    children=[
        html.H2("Worldpanel Dashboard - Symrise"),
        dcc.Tabs(id="regiao-tabs", value=REGIAO_VIEWS[0], children=[dcc.Tab(label=r, value=r) for r in REGIAO_VIEWS]),
        html.Div(
            style={"margin": "16px 0 12px", "maxWidth": "260px"},
            children=[
                html.Label("Quebra por"),
                dcc.Dropdown(
                    id="dimension-dropdown",
                    options=[
                        {"label": "Segmento", "value": "segmento"},
                        {"label": "Fabricante", "value": "fabricante"},
                        {"label": "Marca", "value": "marca"},
                        {"label": "Submarca", "value": "submarca"},
                        {"label": "Variante", "value": "variante"},
                    ],
                    value="segmento",
                    clearable=False,
                ),
            ],
        ),
        html.Div(
            id="top-n-container",
            style={"display": "none", "margin": "0 0 16px"},
            children=[
                html.Label("Ranking (top N por indicador, base 2025)"),
                dcc.RadioItems(
                    id="top-n-selector",
                    options=[{"label": f"Top {n}", "value": n} for n in TOP_N_OPTIONS],
                    value=TOP_N_DEFAULT,
                    inline=True,
                    inputStyle={"marginRight": "4px", "marginLeft": "12px"},
                ),
            ],
        ),
        html.Div(
            style={"display": "flex", "gap": "16px", "marginBottom": "24px", "flexWrap": "wrap"},
            children=[
                html.Div([html.Label("Segmento"), _dropdown("segmento-filter", SEGMENTO_FILTER_OPTIONS, "Total")], style={"flex": "1", "minWidth": "160px"}),
                html.Div([html.Label("Fabricante"), _dropdown("fabricante-filter", FABRICANTE_FILTER_OPTIONS, "Total")], style={"flex": "1", "minWidth": "160px"}),
                html.Div([html.Label("Marca"), _dropdown("marca-filter", ["Total"] + ALL_MARCAS, "Total")], style={"flex": "1", "minWidth": "160px"}),
                html.Div([html.Label("Submarca"), _dropdown("submarca-filter", ["Total"] + ALL_SUBMARCAS, "Total")], style={"flex": "1", "minWidth": "160px"}),
                html.Div([html.Label("Variante"), _dropdown("variante-filter", ["Total"] + ALL_VARIANTES, "Total")], style={"flex": "1", "minWidth": "160px"}),
            ],
        ),
        dcc.Loading(
            type="circle",
            fullscreen=True,
            overlay_style={"visibility": "visible", "opacity": 0.4, "backgroundColor": "white"},
            children=html.Div(children=[_chart_block(key) for key in INDICATOR_BLOCKS]),
        ),
    ],
)


@app.callback(
    Output("marca-filter", "options"),
    Output("marca-filter", "value"),
    Input("fabricante-filter", "value"),
)
def update_marca_options(fabricante_f):
    marcas = ALL_MARCAS if fabricante_f == "Total" else MARCA_BY_FABRICANTE.get(fabricante_f, [])
    return [{"label": o, "value": o} for o in (["Total"] + marcas)], "Total"


@app.callback(
    Output("submarca-filter", "options"),
    Output("submarca-filter", "value"),
    Input("marca-filter", "value"),
)
def update_submarca_options(marca_f):
    submarcas = ALL_SUBMARCAS if marca_f == "Total" else SUBMARCA_BY_MARCA.get(marca_f, [])
    return [{"label": o, "value": o} for o in (["Total"] + submarcas)], "Total"


@app.callback(
    Output("variante-filter", "options"),
    Output("variante-filter", "value"),
    Input("marca-filter", "value"),
)
def update_variante_options(marca_f):
    variantes = ALL_VARIANTES if marca_f == "Total" else VARIANTE_BY_MARCA.get(marca_f, [])
    return [{"label": o, "value": o} for o in (["Total"] + variantes)], "Total"


@app.callback(
    Output("segmento-filter", "disabled"),
    Output("segmento-filter", "options"),
    Output("segmento-filter", "value"),
    Output("fabricante-filter", "disabled"),
    Output("marca-filter", "disabled"),
    Output("submarca-filter", "disabled"),
    Output("variante-filter", "disabled"),
    Input("dimension-dropdown", "value"),
    State("segmento-filter", "value"),
)
def update_filters_disabled(breakdown, segmento_f):
    # Segmento e um eixo independente da cadeia Fabricante>Marca>Submarca>
    # Variante: so fica desabilitado quando ele proprio e a quebra. Dentro
    # da cadeia, um filtro fica disponivel se for mais raso que a quebra
    # ativa (ancestral dela) ou se a quebra for Segmento (a cadeia toda
    # vira filtro); a propria quebra e os niveis mais fundos ficam
    # desabilitados (nao faz sentido fixar Submarca enquanto quebra por
    # Marca, por exemplo).
    def enabled(name):
        if name == "segmento":
            return breakdown != "segmento"
        if breakdown == "segmento":
            return True
        if breakdown == name:
            return False
        return FILTER_DEPTH[name] < FILTER_DEPTH[breakdown]

    # Marca/Submarca/Variante nao existem no agregador Segmento="Total" -
    # a planilha so as detalha dentro de Feminino/Masculino/Infantil/
    # Unisex (Submarca/Variante nao tem nenhuma linha em "Total"; Marca
    # ate tem algumas, mas misturadas com totais de fabricante reaproveitados
    # como "marca" pela descida generica - nao e uma quebra confiavel) -
    # por isso tira "Total" das opcoes e forca um segmento real
    if breakdown in TOP_N_BREAKDOWNS:
        segmento_options = SEGMENTOS
        segmento_value = segmento_f if segmento_f != "Total" else SEGMENTOS[0]
    else:
        segmento_options = SEGMENTO_FILTER_OPTIONS
        segmento_value = segmento_f

    return (
        not enabled("segmento"),
        [{"label": o, "value": o} for o in segmento_options],
        segmento_value,
        not enabled("fabricante"),
        not enabled("marca"),
        not enabled("submarca"),
        not enabled("variante"),
    )


@app.callback(
    Output("top-n-container", "style"),
    Input("dimension-dropdown", "value"),
)
def update_top_n_visibility(breakdown):
    style = {"margin": "0 0 16px"}
    if breakdown not in TOP_N_BREAKDOWNS:
        style["display"] = "none"
    return style


def _chart_height(breakdown, categories):
    """Marca/Submarca/Variante empilham ate 30 categorias (top N) numa
    unica coluna - a altura padrao (640px) nao da espaco suficiente pros
    rotulos de cada uma sem sobrepor perto da base da pilha. Cresce com o
    numero de categorias realmente exibidas, so pra essas 3 quebras."""
    if breakdown not in TOP_N_BREAKDOWNS:
        return 640
    n = len(categories)
    return max(640, min(1500, 640 + max(0, n - 8) * 35))


def _weighted_average(values, weight_values, categories, years=YEARS_DEFAULT):
    """Media ponderada ano a ano de `values` entre `categories`, usando
    `weight_values` (tipicamente Volume) como peso - a linha tracejada
    dos graficos de linha (indicadores nao aditivos, ex.: Preco Medio,
    onde uma media simples entre categorias ignoraria o tamanho de
    cada uma)."""
    result = {}
    for yr in years:
        weight_sum = sum(weight_values.get(cat, {}).get(yr, 0.0) for cat in categories)
        if not weight_sum:
            result[yr] = None
            continue
        result[yr] = sum(
            values.get(cat, {}).get(yr, 0.0) * weight_values.get(cat, {}).get(yr, 0.0) for cat in categories
        ) / weight_sum
    return result


@app.callback(
    [Output(f"graph-{key}", "figure") for key in INDICATOR_BLOCKS]
    + [Output(f"variation-table-{key}", "children") for key in INDICATOR_BLOCKS]
    + [Output(f"insight-text-{key}", "children") for key in INDICATOR_BLOCKS],
    Input("dimension-dropdown", "value"),
    Input("regiao-tabs", "value"),
    Input("segmento-filter", "value"),
    Input("fabricante-filter", "value"),
    Input("marca-filter", "value"),
    Input("submarca-filter", "value"),
    Input("variante-filter", "value"),
    Input("top-n-selector", "value"),
)
def update_charts(breakdown, regiao_view, segmento_f, fabricante_f, marca_f, submarca_f, variante_f, top_n):
    if not breakdown:
        breakdown = "segmento"
    if breakdown not in TOP_N_BREAKDOWNS:
        top_n = _TOP_N

    figs, tables, insights = [], [], []
    # categorias/valores ja resolvidos de cada bloco, indexado por
    # indicador - alimenta os blocos com `rank_with`/`weight_indicator`
    # (ver INDICATORS: "volume" precisa vir antes deles em INDICATOR_BLOCKS)
    resolved_categories: dict[str, list[str]] = {}
    resolved_values: dict[str, dict[str, dict[str, float]]] = {}

    for key in INDICATOR_BLOCKS:
        cfg = INDICATORS[key]
        rank_with = cfg.get("rank_with")
        categories, dim_col, filters, values_override, title, true_totals = build_selection(
            breakdown, regiao_view, segmento_f, fabricante_f, marca_f, submarca_f, variante_f, key, top_n,
            categories_override=resolved_categories.get(rank_with) if rank_with else None,
            weight_indicator=cfg.get("weight_indicator"),
        )
        # resolve os valores uma unica vez (grafico, tabela e insight usam
        # exatamente os mesmos numeros)
        if values_override is not None:
            values = values_override
        elif categories:
            values = compute_values(df, key, dim_col, categories, YEARS_DEFAULT, filters, cfg["value_scale"])
        else:
            values = {}

        resolved_categories[key] = categories
        resolved_values[key] = values

        if cfg.get("chart_type") == "line":
            value_decimals = cfg["value_decimals"]
            insight_unit_label = cfg["unit_label"]
            subtitle = f"{cfg['label']} ({cfg['unit_label']})" if cfg["unit_label"] else cfg["label"]
            weight_key = cfg.get("weight_indicator")
            weighted_average = (
                _weighted_average(values, resolved_values.get(weight_key, {}), categories)
                if weight_key else None
            )
            fig = line_evolution_chart(
                df=df, indicator=key, dimension=dim_col, categories=categories, filters=filters,
                title=title, subtitle=subtitle, unit_label=cfg["unit_label"],
                value_decimals=value_decimals, is_percent=cfg["is_percent"],
                values_override=values, weighted_average=weighted_average,
            )
            fig.update_layout(autosize=True, width=None)
        else:
            values, true_totals, unit, decimals_override = _resolve_unit(key, values, categories, true_totals)
            value_decimals = decimals_override if decimals_override is not None else cfg["value_decimals"]
            insight_unit_label = unit or cfg["unit_label"]
            subtitle = f"{cfg['label']} ({unit})" if unit else cfg["label"]
            # com true_totals (Submarca/Variante = so um recorte top N), o
            # "total" que apareceria no topo da barra/na variacao do total
            # seria so a soma do recorte exibido, nao o total real - por
            # isso o grafico omite os dois nesse caso
            show_total = true_totals is None

            fig = alluvial_stack_chart(
                df=df, indicator=key, dimension=dim_col, categories=categories, filters=filters,
                title=title, subtitle=subtitle, values_override=values,
                value_scale=1.0, value_decimals=value_decimals, is_percent=cfg["is_percent"],
                show_total=show_total, height=_chart_height(breakdown, categories),
            )
            fig.update_layout(autosize=True, width=None)

        table = _variation_table(categories, values, cfg["additive"], value_decimals, true_totals)

        insight = generate_insight(
            df, indicator=key, dimension=dim_col, categories=categories, filters=filters,
            value_scale=1.0, value_decimals=value_decimals, unit_label=insight_unit_label,
            additive=cfg["additive"], values_override=values, totals_override=true_totals,
        )
        figs.append(fig)
        tables.append(table)
        insights.append(insight)

    return (*figs, *tables, *insights)


if __name__ == "__main__":
    app.run(debug=True)
