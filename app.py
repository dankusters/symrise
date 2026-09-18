"""App Dash do dashboard Worldpanel: view principal por Regiao (abas),
com filtros cruzaveis (Segmento, Fabricante, Marca, Submarca, Variante,
Sub Variante) e um "Quebra por" que escolhe qual dessas dimensoes vira as categorias
empilhadas do grafico - as demais ficam fixas como filtro de valor
unico. Cada view de regiao traz 3 blocos fixos (grafico + highlight):
Volume, Unidades e Valor com Presentes.

Rodar localmente:
    python app.py
"""

from __future__ import annotations

import os
import re

from dash import Dash, Input, Output, State, ctx, dcc, html

from charts import (
    YEARS_DEFAULT,
    alluvial_stack_chart,
    compute_values,
    compute_variations,
    line_evolution_chart,
    price_unit_waterfall_chart,
    unit_additions_bridge_chart,
)
from etl import build_dataset, load_category_exceptions
from export_pptx import TABLE_LEGEND_NO_SHARE, TABLE_LEGEND_WITH_SHARE, build_additions_pptx, build_price_unit_pptx, build_pptx
from insights import generate_insight, generate_price_unit_insight, generate_unit_additions_insight

df = build_dataset()

REGIAO_VIEWS = ["T. Brasil", "Sudeste", "C.Oeste", "Sul", "N+NE"]

# aba extra ao lado das views de Regiao (REGIAO_VIEWS): em vez de fixar
# uma regiao e quebrar por Segmento/Fabricante/etc, quebra o mercado
# INTEIRO (Segmento/Fabricante/Marca = "Total", ver _regiao_root_values)
# pelas proprias regioes - pesos e variacoes por regiao. Nao e um valor
# de REGIAO_VIEWS porque nao fixa regiao nenhuma; "Quebra por" e todos
# os filtros ficam desabilitados (nao combinam com essa quebra, ver
# update_filters_disabled/update_dimension_dropdown_disabled). Exclui
# "T. Brasil" das categorias exibidas (e a soma das outras 4, entraria
# como mais uma barra dentro do proprio total).
REGIOES_TAB_KEY = "Regiões"
REGIOES_BREAKDOWN_CATEGORIES = [r for r in REGIAO_VIEWS if r != "T. Brasil"]
SEGMENTOS = ["Feminino", "Masculino", "Infantil", "Unisex"]

SEGMENTO_FILTER_OPTIONS = ["Total"] + SEGMENTOS

# filtro adicional independente, so faz sentido combinado com quebra por
# Submarca/Variante/Sub Variante: a classificacao (fonte/body_splash.xlsx,
# aba "2025", coluna IsBodySplash, juntada por Cod. em etl.load_body_splash)
# so marca "Sim" em linhas desses 3 niveis (e seus residuais "Outros X") -
# nenhum Fabricante/Marca inteiro e 100% Body Splash, entao filtrar por
# esses niveis daria numeros vazios/errados (ver update_filters_disabled)
BODY_SPLASH_OPTIONS = ["Total", "Sim", "Não"]
BODY_SPLASH_BREAKDOWNS = ("submarca", "variante", "subvariante")
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
# Sub Variante: nivel abaixo de Variante, so existe pra 2 marcas (Natura,
# Boticario - ver conversa com o usuario) - mesmo esquema flatten-por-
# marca das demais (o dropdown, quando Marca esta fixo, mostra todas as
# sub-variantes daquela marca, sem filtrar por Variante tambem, igual
# Submarca/Variante ja fazem)
SUBVARIANTE_BY_MARCA: dict[str, list[str]] = (
    df.loc[df["classificacao"] == "Sub Variante"].groupby("marca")["rotulo"].unique().apply(sorted).to_dict()
)

# listas completas, usadas quando o filtro pai (Fabricante/Marca) esta em
# "Total" - o dropdown do filho continua oferecendo todo mundo
ALL_MARCAS = sorted(df.loc[df["classificacao"] == "Marca", "marca"].unique())
ALL_SUBMARCAS = sorted(df.loc[df["classificacao"] == "Sub Marca", "rotulo"].unique())
ALL_VARIANTES = sorted(df.loc[df["classificacao"] == "Variante", "rotulo"].unique())
ALL_SUBVARIANTES = sorted(df.loc[df["classificacao"] == "Sub Variante", "rotulo"].unique())

# ExtendCategory (ver etl.load_category_exceptions/conversa sobre WePink,
# Granado, Granado Bebe, Phebo): entidades "sem filhos" na arvore (a
# quebra ja mostra elas certo em qualquer nivel, via o fallback generico
# de folha em _descend_scoped) que ficam TAMBEM selecionaveis como
# filtro em niveis mais fundos do que a classificacao original permite -
# ex.: WePink (Fabricante) tambem funciona como filtro de Marca/
# Submarca. EXTENDED_NAMES reindexa `_extensions_by_cod` (vindo por Cod.)
# pelo nome de exibicao (coluna "marca", que pra essas entidades ja e a
# mesma nos dois papeis - fabricante="WePink" e marca="WePink"), pra
# poder re-resolver o cod em QUALQUER regiao/segmento onde esse nome
# aparecer (ver _self_cod), nao so na linha de exemplo da planilha de
# excecoes.
_, IGNORE_CODS, _extensions_by_cod, CATEGORY_CHANGES = load_category_exceptions()
# {nome: (classificacao nativa, niveis extras)} - guarda a classificacao
# nativa tambem (nao so o nome) porque o mesmo nome de "marca" pode
# aparecer em mais de uma linha (ex.: "Granado" e o nome tanto do
# Fabricante-raiz "T. Granado" quanto da Marca "Granado" em si) - sem
# isso, o fallback de _self_cod poderia resolver pro cod errado (o
# Fabricante inteiro, nao so a entidade sendo estendida)
EXTENDED_NAMES: dict[str, tuple[str, frozenset[str]]] = {}
for _ext_cod, _ext_labels in _extensions_by_cod.items():
    _ext_rows = df.loc[df["cod"] == _ext_cod, ["marca", "classificacao"]]
    if not _ext_rows.empty:
        _ext_name = _ext_rows["marca"].iloc[0]
        EXTENDED_NAMES[_ext_name] = (_ext_rows["classificacao"].iloc[0], _ext_labels)

for _ext_name, (_ext_native, _ext_labels) in EXTENDED_NAMES.items():
    if "Marca" in _ext_labels:
        if _ext_name not in ALL_MARCAS:
            ALL_MARCAS = sorted(ALL_MARCAS + [_ext_name])
        MARCA_BY_FABRICANTE.setdefault(_ext_name, [])
        if _ext_name not in MARCA_BY_FABRICANTE[_ext_name]:
            MARCA_BY_FABRICANTE[_ext_name] = sorted(MARCA_BY_FABRICANTE[_ext_name] + [_ext_name])
    if "Sub Marca" in _ext_labels:
        if _ext_name not in ALL_SUBMARCAS:
            ALL_SUBMARCAS = sorted(ALL_SUBMARCAS + [_ext_name])
        SUBMARCA_BY_MARCA.setdefault(_ext_name, [])
        if _ext_name not in SUBMARCA_BY_MARCA[_ext_name]:
            SUBMARCA_BY_MARCA[_ext_name] = sorted(SUBMARCA_BY_MARCA[_ext_name] + [_ext_name])
    if "Variante" in _ext_labels:
        if _ext_name not in ALL_VARIANTES:
            ALL_VARIANTES = sorted(ALL_VARIANTES + [_ext_name])
        VARIANTE_BY_MARCA.setdefault(_ext_name, [])
        if _ext_name not in VARIANTE_BY_MARCA[_ext_name]:
            VARIANTE_BY_MARCA[_ext_name] = sorted(VARIANTE_BY_MARCA[_ext_name] + [_ext_name])
    if "Sub Variante" in _ext_labels:
        if _ext_name not in ALL_SUBVARIANTES:
            ALL_SUBVARIANTES = sorted(ALL_SUBVARIANTES + [_ext_name])
        SUBVARIANTE_BY_MARCA.setdefault(_ext_name, [])
        if _ext_name not in SUBVARIANTE_BY_MARCA[_ext_name]:
            SUBVARIANTE_BY_MARCA[_ext_name] = sorted(SUBVARIANTE_BY_MARCA[_ext_name] + [_ext_name])

# ordem da cadeia Fabricante > Marca > Sub Marca > Variante > Sub
# Variante, usada pra decidir quais filtros ficam habilitados pra cada
# quebra (Segmento e um eixo independente, tratado a parte)
FILTER_DEPTH = {"fabricante": 1, "marca": 2, "submarca": 3, "variante": 4, "subvariante": 5}

# quebras derivadas das arvores "T. Embalagem" (cod '3': Refil/Nao
# Refil) e "T. Conteudos" (cod '4': faixas de volume da embalagem) -
# filhas diretas de T. Perfumaria (cod '1'), paralelas a Segmento (cod
# '2'/'6') e Fabricante (cod '5'). Nao documentadas no ESCOPO.md;
# descobertas direto na planilha - as 135 linhas dessas duas arvores tem
# SEMPRE Segmento=Fabricante=Marca="Total": so combinam com Regiao,
# nunca com as demais dimensoes (ver conversa com o usuario). Cada
# entrada: (cod pai, rotulo do "Quebra por").
EMBALAGEM_BREAKDOWNS = {
    "embalagem_tipo": ("3", "Embalagem (Tipo)"),
    "embalagem_conteudo": ("4", "Embalagem (Conteúdo)"),
}

# indicadores fixos exibidos nas views (ESCOPO.md secao 3): 3 blocos
# empilhaveis (chart_type="stack", metadados usados por
# alluvial_stack_chart) + os graficos de linha (chart_type="line", nao
# cumulativos - ver line_evolution_chart), que entram um de cada vez.
# "volume" precisa ficar antes de qualquer indicador com `rank_with`
# nesta lista (ver update_charts: as categorias de "rank_with" so estao
# disponiveis apos o bloco correspondente ja ter sido processado).
INDICATOR_BLOCKS = [
    "volume", "unidades", "valor_com_presentes", "compradores",
    "penetracao", "vol_por_comprador", "frequencia", "preco_medio_litros",
]

# aba a parte (nao entra em INDICATOR_BLOCKS/update_charts): um waterfall
# por categoria em vez de um unico grafico com todas juntas - ver
# update_waterfall
PRICE_UNIT_TAB_KEY = "price_unit"
PRICE_UNIT_TAB_LABEL = "Price/Unit"

# abas "Adicoes de X": bridge/waterfall de UMA UNICA transicao (o
# penultimo -> ultimo ano de YEARS_DEFAULT, hoje 2024->2025 - nao o
# periodo inteiro, decidido apos o usuario achar a versao com as 4
# transicoes de 2021 em diante extensa demais) decompondo a diferenca
# do indicador entre os dois anos por categoria (Fabricante/Marca/etc)
# - ver _build_additions_bridge. O rotulo da aba ja reforca o periodo
# coberto. Cada entrada de ADDITIONS_TABS gera uma aba identica (mesmo
# grafico/tabela/highlight, ver _additions_panel/_additions_tab_result),
# so trocando o indicador - "unit_additions" (Unidades) e "value_additions"
# (Valor com Presentes) nessa ordem, que e a ordem visual das abas.
ADDITIONS_YEAR0 = YEARS_DEFAULT[-2]
ADDITIONS_YEAR1 = YEARS_DEFAULT[-1]
ADDITIONS_TABS = [
    dict(
        key="unit_additions",
        indicator="unidades",
        tab_label=f"Adições de Unidades {ADDITIONS_YEAR0[1:]}→{ADDITIONS_YEAR1[1:]}",
        chart_unit_label="milhões de unidades",
        insight_label="Unidades",
        graph_id="graph-unit-additions",
        table_id="unit-additions-table",
        insight_id="unit-additions-insight",
    ),
    dict(
        key="value_additions",
        indicator="valor_com_presentes",
        tab_label=f"Adições de Valor com Presente {ADDITIONS_YEAR0[1:]}→{ADDITIONS_YEAR1[1:]}",
        chart_unit_label="R$ milhões",
        insight_label="Valor com Presentes",
        graph_id="graph-value-additions",
        table_id="value-additions-table",
        insight_id="value-additions-insight",
    ),
]
INDICATORS = {
    "volume": dict(label="Volume", value_scale=1e-6, value_decimals=2, unit_label="milhões de litros", is_percent=False, additive=True, chart_type="stack"),
    "unidades": dict(label="Unidades (milhões)", value_scale=1e-6, value_decimals=2, unit_label="milhões", is_percent=False, additive=True, chart_type="stack"),
    "valor_com_presentes": dict(label="Valor com Presentes", value_scale=1e-6, value_decimals=2, unit_label="R$ milhões", is_percent=False, additive=True, chart_type="stack"),
    "compradores": dict(label="Compradores (milhões)", value_scale=1e-6, value_decimals=2, unit_label="milhões", is_percent=False, additive=True, chart_type="stack"),
    # Penetracao/Vol. por Comprador/Frequencia sao indicadores de
    # taxa/media (ESCOPO.md secao 3) - nao aditivos entre categorias
    # (ex.: penetracao de Natura + penetracao de Boticario NAO e a
    # penetracao do fabricante somado), por isso chart_type="line" (sem
    # empilhar) e reaproveitam o ranking de Volume (`rank_with`), mesmo
    # racional do Preco Medio: rankear pelo proprio valor poderia por
    # uma categoria de volume minusculo no topo so por ter, por
    # exemplo, frequencia de compra alta numa base pequena de
    # compradores. Sem `weight_indicator`/`average_mode`: ao contrario
    # do Preco Medio, nao ha uma media (simples ou ponderada) obvia pra
    # essas 3 - a linha tracejada fica de fora.
    "penetracao": dict(label="Penetração", value_scale=1.0, value_decimals=1, unit_label="", is_percent=True, additive=False, chart_type="line", rank_with="volume"),
    "vol_por_comprador": dict(label="Vol. por Comprador", value_scale=1.0, value_decimals=1, unit_label="litros", is_percent=False, additive=False, chart_type="line", rank_with="volume"),
    "frequencia": dict(label="Frequência", value_scale=1.0, value_decimals=1, unit_label="", is_percent=False, additive=False, chart_type="line", rank_with="volume"),
    # nao aditivo (preco medio nao se soma entre categorias) - por isso
    # reaproveita o ranking/categorias ja escolhidas no bloco de Volume
    # (`rank_with`) em vez de rankear pelo proprio preco (uma marca de
    # nicho com preco unitario alto poderia "assumir" o topo so por
    # causa do preco); a ponderacao por Volume (`weight_indicator`) segue
    # dando o valor da categoria sintetica "Demais outras"/"Outras" (media
    # ponderada do que sobrou, nunca soma - preco medio nao e aditivo) -
    # mas a linha tracejada do grafico usa media SIMPLES (`average_mode`),
    # pra olhar o nivel de preco em si, sem marcas de maior volume vendido
    # puxarem a media
    "preco_medio_litros": dict(
        label="Preço Médio (Litros)", value_scale=1.0, value_decimals=2, unit_label="R$/litro",
        is_percent=False, additive=False, chart_type="line", rank_with="volume", weight_indicator="volume",
        average_mode="simple",
    ),
}

# indicadores cujo rotulo de unidade alterna entre milhoes/bilhoes
# conforme o total exibido - sem isso, um total grande (ex.: Valor com
# Presentes do mercado inteiro) aparecia como "19031.7 (R$ milhoes)" em
# vez de "19.0 (R$ bilhoes)". Cada entrada: (rotulo em milhoes, rotulo
# em bilhoes, casas decimais quando em bilhoes)
DYNAMIC_UNIT = {
    "volume": ("milhões de litros", "bilhões de litros", 2),
    "valor_com_presentes": ("R$ milhões", "R$ bilhões", 2),
}
_BILLION_THRESHOLD = 1000.0  # valores ja vem em milhoes; 1000 milhoes = 1 bilhao

_TOP_N = 6

# quebras que descobrem categorias dinamicamente (Marca/Submarca/Variante
# podem ter dezenas de itens) ganham um seletor de quantos mostrar,
# sempre rankeados pelo ultimo ano (2025) de cada indicador
TOP_N_BREAKDOWNS = ("marca", "submarca", "variante", "subvariante")
TOP_N_OPTIONS = [10, 20, 30]
TOP_N_DEFAULT = TOP_N_OPTIONS[0]

# quebra "Body Splash" (ver BODY_SPLASH_BREAKDOWN_KEY/_body_splash_values):
# 2 categorias fixas (Body Splash x Nao Body Splash) que somam 100% do
# indicador no filtro atual - ranking nao faz sentido aqui (so 2
# categorias, nunca um top N), por isso NAO entra em TOP_N_BREAKDOWNS.
# Mas assim como as 4 quebras acima, so existe detalhamento por
# is_body_splash dentro de um Segmento real (ver comentario logo abaixo,
# sobre Submarca/Variante/Sub Variante nao existirem em Segmento="Total")
# - por isso combina com TOP_N_BREAKDOWNS nesse forcing de Segmento em
# update_filters_disabled.
BODY_SPLASH_BREAKDOWN_KEY = "bodysplash"
SEGMENT_REQUIRED_BREAKDOWNS = TOP_N_BREAKDOWNS + (BODY_SPLASH_BREAKDOWN_KEY,)

# Fabricante tambem ganha um seletor de ranking, com opcoes proprias (a
# arvore de fabricantes e bem mais rasa que Marca/Submarca/Variante) e um
# checkbox a parte pra incluir ou nao o bloco sintetico "Demais
# Fabricantes" (ver _rank_top_n/other_label em build_selection). Com o
# checkbox desmarcado, a soma das categorias exibidas passa a ser so o
# top N filtrado (nao fecha mais o mercado real) - mesmo tratamento que
# Marca/Submarca/Variante ja tem (true_totals cobre a diferenca pra %
# de participacao/insights, ver `true_totals` em `build_selection`)
FABRICANTE_TOP_N_OPTIONS = [5, 6, 10]
FABRICANTE_TOP_N_DEFAULT = _TOP_N

# quebras cujo seletor de ranking (top-n-container) aparece na UI
RANKED_BREAKDOWNS = TOP_N_BREAKDOWNS + ("fabricante",)

app = Dash(__name__, url_base_pathname=os.environ.get("DASH_URL_BASE_PATHNAME", "/"))
app.title = "Kantar Worldpanel - Dashboard"


# _scope/_cod_children sao o par mais chamado de toda a navegacao por
# Cod. (todo build_selection/_descend_to_level passa por eles, muitas
# vezes por callback - um por indicador, ver INDICATOR_BLOCKS) e `df`
# nunca muda em runtime (carregado uma unica vez no import, ver
# `build_dataset()` acima), entao o resultado de cada um e sempre o
# mesmo pra uma combinacao de argumentos - seguro cachear pra sempre,
# sem invalidacao. Perfilando uma troca de "Quebra por Marca", isso e
# que dominava o tempo do callback (~1.5s de ~4.7s, batendo o mesmo
# subconjunto de linhas do zero uma vez por indicador).
_scope_cache: dict[tuple[tuple[str, str], ...], "pd.DataFrame"] = {}
_cod_children_cache: dict[tuple[int, str], "pd.DataFrame"] = {}


def _scope(base_filters):
    """Aplica `base_filters` (regiao/segmento, tipicamente) uma unica vez
    sobre `df` - usado como ponto de partida tanto por buscas de um nivel
    so quanto pela descida recursiva de `_descend_to_level`, que reusa o
    mesmo subset em vez de refiltrar regiao/segmento a cada passo.
    Cacheado por combinacao de filtros (ver `_scope_cache` acima) -
    devolve sempre o MESMO objeto DataFrame pra argumentos iguais, o que
    tambem estabiliza `id(scoped_df)` entre chamadas pra `_cod_children`
    reaproveitar seu proprio cache."""
    key = tuple(sorted(base_filters.items()))
    cached = _scope_cache.get(key)
    if cached is not None:
        return cached
    subset = df
    for col, val in base_filters.items():
        subset = subset[subset[col] == val]
    _scope_cache[key] = subset
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
    seja qual for o rotulo de classificacao da linha.

    Cacheado por (id(scoped_df), parent_cod) - seguro porque `scoped_df`
    so vem de `_scope`, que mantem uma referencia permanente (o id nunca
    e reciclado pro tempo de vida do processo) e sempre devolve o mesmo
    objeto pra um `base_filters` ja visto."""
    key = (id(scoped_df), parent_cod)
    cached = _cod_children_cache.get(key)
    if cached is not None:
        return cached
    pattern = re.compile(rf"^{re.escape(parent_cod)}\.\d+$")
    result = scoped_df[scoped_df["cod"].str.match(pattern)]
    _cod_children_cache[key] = result
    return result


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
    recalculado a partir do que sobrou fora das categorias mostradas:
    media ponderada por `weight_all` (tipicamente Volume) quando dado -
    nunca somada, pois nao faz sentido somar precos medios/indicadores
    nao aditivos - ou, se `weight_all` nao for dado, a SOMA do que
    sobrou (correto quando este proprio indicador e aditivo, ex.:
    Unidades reaproveitando o ranking de Valor com Presentes)."""
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
        elif leftover_keys:
            values[cat] = {yr: sum(values_all[k][yr] for k in leftover_keys) for yr in YEARS_DEFAULT}
        else:
            values[cat] = {yr: 0.0 for yr in YEARS_DEFAULT}
    return categories, values


def discover_top_categories(
    indicator, dim_col, base_filters, parent_cod, other_label="Outras", top_n=_TOP_N,
    categories_override=None, weight_indicator=None, add_other=True,
):
    """Top N filhos diretos de `parent_cod` (ultimo ano) + (se `add_other`)
    um grupo sintetico com o restante, pra barra fechar o total real. Com
    `add_other=False` o resto do ranking e descartado (ver `_rank_top_n`)."""
    if not parent_cod:
        return [], {}
    values_all = _children_values(indicator, dim_col, base_filters, parent_cod)
    weight_all = _children_values(weight_indicator, dim_col, base_filters, parent_cod) if weight_indicator else None
    return _apply_ranking(
        values_all, top_n, other_label, add_other=add_other, categories_override=categories_override, weight_all=weight_all,
    )


def _descend_scoped(scale, dim_col, scoped_df, start_cod, target_classificacoes, exclude_classificacoes, year_cols, result, add, body_splash_f="Total"):
    rows = _cod_children(scoped_df, start_cod)
    if rows.empty:
        return False
    if exclude_classificacoes:
        rows = rows[~rows["classificacao"].isin(exclude_classificacoes)]
        if rows.empty:
            return True  # existiam filhos, so que todos excluidos - nao e uma folha "sem dados"

    # IGNORE_CODS (ver etl.load_category_exceptions/"IgnoreAtAll"): esses
    # cods nunca viram categoria propria em nenhuma quebra, mesmo que a
    # classificacao (original ou reclassificada) bata com o alvo - so
    # reforca pra quando o pai no Cod. nao compartilha o mesmo rotulo
    # novo (ver docstring de load_category_exceptions); a descida
    # continua normal pros filhos deles logo abaixo.
    at_target = rows["classificacao"].isin(target_classificacoes) & ~rows["cod"].isin(IGNORE_CODS)
    direct = rows[at_target]
    # filtro IsBodySplash (ver BODY_SPLASH_OPTIONS): so restringe as
    # linhas que de fato VIRAM categoria (aqui e no fallback de folha
    # abaixo) - nunca a travessia da arvore (fabricante/marca continuam
    # sendo descidos por inteiro, so o resultado final e que so mostra
    # quem bate com a classificacao escolhida)
    if body_splash_f != "Total" and not direct.empty:
        direct = direct[direct["is_body_splash"] == body_splash_f]
    if not direct.empty:
        grouped = direct.assign(_disp=_display_names(direct, dim_col)).groupby("_disp")[year_cols].sum()
        for name, row_sum in zip(grouped.index, grouped.itertuples(index=False)):
            for yr, value in zip(YEARS_DEFAULT, row_sum):
                add(name, yr, float(value) * scale)

    for row in rows[~at_target].itertuples():
        found = _descend_scoped(scale, dim_col, scoped_df, row.cod, target_classificacoes, exclude_classificacoes, year_cols, result, add, body_splash_f)
        if not found:
            if row.cod in IGNORE_CODS:
                continue  # ignorado (ver IGNORE_CODS acima): folha sem filhos, mas nunca vira categoria propria
            # ExtendCategory (ver EXTENDED_NAMES): uma entidade "sem
            # filhos" registrada so conta como categoria propria ate o
            # nivel mais fundo que ela foi estendida (nativo +
            # ExtendCategory) - alem disso (ex.: WePink numa quebra por
            # Variante, so estendida ate Sub Marca) ela e ignorada
            # tambem, mesmo sendo uma folha de verdade - sem essa
            # checagem o fallback abaixo a mostraria em QUALQUER nivel
            # (toda folha sem filhos vira categoria propria por padrao).
            extended = EXTENDED_NAMES.get(row.marca)
            if extended and not (target_classificacoes & ({extended[0]} | extended[1])):
                continue
            if body_splash_f != "Total" and row.is_body_splash != body_splash_f:
                continue  # folha que nao bate com o filtro IsBodySplash
            # folha antes de chegar no nivel alvo (a planilha nao detalha
            # mais fundo aqui) - a propria linha e o que ha pra mostrar
            name = getattr(row, dim_col)
            if name == "Total":
                name = getattr(row, "rotulo")
            if name in EXCLUDE_NAMES_FROM_RANKING:
                continue
            for yr, col in zip(YEARS_DEFAULT, year_cols):
                add(name, yr, float(getattr(row, col)) * scale)

    return True


def _descend_to_level(indicator, dim_col, base_filters, start_cod, target_classificacoes, exclude_classificacoes=frozenset(), body_splash_f="Total"):
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

    _descend_scoped(scale, dim_col, scoped_df, start_cod, target_classificacoes, exclude_classificacoes, year_cols, result, _add, body_splash_f)
    return result


_BODY_SPLASH_LABEL = "Body Splash"
_NOT_BODY_SPLASH_LABEL = "Não Body Splash"


def _body_splash_leaves(scoped_df, cod, year_cols, buckets, scale):
    """Desce recursivamente ate as FOLHAS DE VERDADE da arvore de Cod.
    sob `cod` (sem parar num nivel-alvo, ao contrario de
    `_descend_scoped`/`_descend_to_level`) somando o indicador de cada
    folha num dos 2 baldes fixos (`_BODY_SPLASH_LABEL`/
    `_NOT_BODY_SPLASH_LABEL`), conforme sua coluna `is_body_splash`
    ("Sim"/"Não" - ver `etl.load_body_splash`). Cobre 100% do escopo
    (sem top N nem residual "Outras"), entao os 2 baldes sempre fecham o
    total real do filtro atual - por isso a quebra "Body Splash" nao usa
    `_apply_ranking`/TOP_N_BREAKDOWNS."""
    rows = _cod_children(scoped_df, cod)
    if rows.empty:
        return False
    for row in rows.itertuples():
        found = _body_splash_leaves(scoped_df, row.cod, year_cols, buckets, scale)
        if not found:
            bucket = _BODY_SPLASH_LABEL if row.is_body_splash == "Sim" else _NOT_BODY_SPLASH_LABEL
            for yr, col in zip(YEARS_DEFAULT, year_cols):
                buckets[bucket][yr] += float(getattr(row, col)) * scale
    return True


def _body_splash_values(indicator, base_filters, start_cod):
    """{"Body Splash"/"Não Body Splash": {ano: valor}} pra quebra
    BODY_SPLASH_BREAKDOWN_KEY: soma o indicador de TODAS as folhas da
    arvore de Cod. sob `start_cod` (o mesmo `start_cod` em cascata usado
    pelas quebras Marca/Submarca/Variante/Sub Variante, ver
    `build_selection` - Fabricante/Marca/Submarca/Variante fixos
    restringem o escopo antes da descida), classificadas por
    `is_body_splash`. Ao contrario de `_descend_to_level`, nao para num
    nivel-alvo: desce ate a folha de verdade, entao cobre 100% do
    volume/valor do escopo, comparavel com o Total exibido nas demais
    quebras (Segmento, Fabricante etc).

    Quando o proprio `start_cod` ja e uma folha (sem filhos - ex.:
    Segmento "Unisex", que na planilha nao se abre em Fabricante/Marca),
    `_body_splash_leaves` nao teria ninguem pra classificar (so filhos
    viram balde, nunca o `start_cod` recebido); esse caso conta a
    PROPRIA linha, senao o total do escopo sumiria (viraria 0 nos dois
    baldes em vez do valor real)."""
    buckets = {_BODY_SPLASH_LABEL: {yr: 0.0 for yr in YEARS_DEFAULT}, _NOT_BODY_SPLASH_LABEL: {yr: 0.0 for yr in YEARS_DEFAULT}}
    if not start_cod:
        return buckets
    scoped_df = _scope(base_filters)
    scale = INDICATORS[indicator]["value_scale"]
    year_cols = [f"{indicator}_{yr}" for yr in YEARS_DEFAULT]
    has_children = _body_splash_leaves(scoped_df, start_cod, year_cols, buckets, scale)
    if not has_children:
        row = scoped_df[scoped_df["cod"] == start_cod]
        if not row.empty:
            row = row.iloc[0]
            bucket = _BODY_SPLASH_LABEL if row["is_body_splash"] == "Sim" else _NOT_BODY_SPLASH_LABEL
            for yr in YEARS_DEFAULT:
                buckets[bucket][yr] += float(row[f"{indicator}_{yr}"]) * scale
    return buckets


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


def _regiao_root_values(
    indicator, segmento_f="Total", fabricante_f="Total", marca_f="Total", submarca_f="Total",
    variante_f="Total", subvariante_f="Total", body_splash_f="Total",
):
    """{regiao: {ano: valor}} do escopo atual (Segmento/Fabricante/Marca/
    Submarca/Variante/Sub Variante/IsBodySplash - todos filtros livres,
    ver update_filters_disabled) em cada regiao real de
    REGIOES_BREAKDOWN_CATEGORIES - usado pela aba "Regioes" (ver
    REGIOES_TAB_KEY), que quebra os indicadores por regiao em vez de
    Segmento/Fabricante/etc. Sem nenhum filtro fixo (todos em "Total"),
    `_selection_start_cod` cai no agregador raiz (cod '1'/'5'/'6', todos
    com o mesmo valor proprio - o total do mercado inteiro).

    IsBodySplash so e aplicado quando o filtro mais fundo da cadeia
    (Submarca/Variante/Sub Variante) esta fixo - e so nesses niveis que
    a classificacao existe de verdade (mesma restricao de
    BODY_SPLASH_BREAKDOWNS); fora disso o filtro fica travado em "Total"
    pela UI, mas o parametro e ignorado aqui tambem por seguranca."""
    body_splash_active = body_splash_f in (_BODY_SPLASH_LABEL, _NOT_BODY_SPLASH_LABEL) and (
        (submarca_f and submarca_f != "Total") or (variante_f and variante_f != "Total")
        or (subvariante_f and subvariante_f != "Total")
    )
    values = {}
    for regiao in REGIOES_BREAKDOWN_CATEGORIES:
        start_cod = _selection_start_cod(
            regiao, segmento_f, fabricante_f, marca_f, submarca_f, variante_f, subvariante_f,
        )
        base_filters = {"regiao": regiao, "segmento": segmento_f}
        if body_splash_active:
            values[regiao] = _body_splash_values(indicator, base_filters, start_cod)[body_splash_f]
        else:
            values[regiao] = _cod_own_values(indicator, start_cod, base_filters)
    return values


def _self_cod(regiao_view, segmento_f, classificacao, fabricante=None, marca=None, rotulo=None):
    """Cod. da linha 'auto-total' de uma entidade (ex.: a propria linha
    Marca=Eudora), usado como `parent_cod` pra buscar os filhos dela.

    Quando a busca estrita (por `classificacao`) nao acha nada, tenta
    EXTENDED_NAMES (ver ExtendCategory/conversa sobre WePink/Granado/
    Phebo): entidades "sem filhos" registradas como tambem validas num
    nivel mais fundo do que a classificacao original delas - reconsulta
    `df` pelo nome (coluna "marca", que pra essas entidades e a mesma
    em qualquer papel) na MESMA regiao/segmento pedidos, sem exigir
    `classificacao`, entao funciona em qualquer combinacao onde esse
    nome tiver uma linha - nao so no exemplo da planilha de excecoes.

    "Total" (o placeholder de filtro nao fixado) conta como None em
    fabricante/marca/rotulo, nunca como valor literal pra filtrar -
    um chamador pode pedir Marca="Boticario" com Fabricante ainda em
    "Total" (o usuario pulou direto pro dropdown de Marca sem passar
    pelo de Fabricante primeiro, ver update_marca_options), e a propria
    linha de Boticario tem fabricante="Boticario" (nunca "Total") -
    exigir a igualdade literal aqui so faria a busca falhar sempre
    nesse caso (ver conversa com o usuario, print de quebra por
    Segmento com Marca=Boticario zerada)."""
    subset = df[
        (df["regiao"] == regiao_view) & (df["segmento"] == segmento_f) & (df["classificacao"] == classificacao)
    ]
    if fabricante is not None and fabricante != "Total":
        subset = subset[subset["fabricante"] == fabricante]
    if marca is not None and marca != "Total":
        subset = subset[subset["marca"] == marca]
    if rotulo is not None and rotulo != "Total":
        subset = subset[subset["rotulo"] == rotulo]
    if not subset.empty:
        return subset["cod"].iloc[0]

    name = rotulo if rotulo is not None else marca if marca is not None else fabricante
    extended = EXTENDED_NAMES.get(name)
    if extended and classificacao in extended[1]:
        native_classificacao = extended[0]
        ext_subset = df[
            (df["regiao"] == regiao_view) & (df["segmento"] == segmento_f)
            & (df["marca"] == name) & (df["classificacao"] == native_classificacao)
        ]
        if not ext_subset.empty:
            return ext_subset["cod"].iloc[0]
    return None


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


def _selection_start_cod(regiao_view, segmento_f, fabricante_f, marca_f, submarca_f, variante_f, subvariante_f):
    """Cod. do no "proprio" da cadeia Fabricante > Marca > Sub Marca >
    Variante > Sub Variante, parando no nivel mais fundo fixado (ou no
    agregador de fabricantes do segmento, se nenhum estiver fixo) - mesma
    cascata usada pelas quebras Body Splash e Sub Variante em
    `build_selection`. Usado pela aba "Regioes" (ver REGIOES_TAB_KEY)
    pra achar, em cada regiao, a linha cujo valor "proprio" corresponde
    aos filtros atuais, antes de quebrar por regiao."""
    if subvariante_f and subvariante_f != "Total":
        return _self_cod(regiao_view, segmento_f, "Sub Variante", marca=marca_f, rotulo=subvariante_f)
    if variante_f and variante_f != "Total":
        return _self_cod(regiao_view, segmento_f, "Variante", marca=marca_f, rotulo=variante_f)
    if submarca_f and submarca_f != "Total":
        return _self_cod(regiao_view, segmento_f, "Sub Marca", marca=marca_f, rotulo=submarca_f)
    if marca_f and marca_f != "Total":
        return _self_cod(regiao_view, segmento_f, "Marca", fabricante=fabricante_f, marca=marca_f)
    if fabricante_f and fabricante_f != "Total":
        return _self_cod(regiao_view, segmento_f, "Fabricante", fabricante=fabricante_f)
    return _fabricante_root_cod(regiao_view, segmento_f)


def _native_classificacao(name, default):
    """Classificacao a usar num filtro exato de `df` pra `name` - a
    "oficial" (`default`) pra entidades normais, ou a NATIVA (ver
    EXTENDED_NAMES/ExtendCategory) quando `name` e uma entidade "sem
    filhos" registrada como tambem valida em `default` mas classificada
    de verdade num nivel mais raso (ex.: Granado e "Marca", nao "Sub
    Marca", mesmo selecionavel como Submarca) - sem isso, um filtro
    exato por `classificacao == default` nao acharia a linha dela."""
    extended = EXTENDED_NAMES.get(name)
    return extended[0] if extended and default in extended[1] else default


def _scope_filters(fabricante_f, marca_f, submarca_f, variante_f, subvariante_f):
    """Filtros de Fabricante/Marca/Submarca/Variante/Sub Variante/
    Classificacao usados quando a quebra do grafico e Segmento (isto e,
    essas dimensoes ficam fixas no nivel mais profundo escolhido, e
    Segmento vira a dimensao variavel)."""
    for value, default in (
        (subvariante_f, "Sub Variante"),
        (variante_f, "Variante"),
        (submarca_f, "Sub Marca"),
    ):
        if not value or value == "Total":
            continue
        extended = EXTENDED_NAMES.get(value)
        if extended and default in extended[1]:
            # entidade "sem filhos" (ver ExtendCategory/EXTENDED_NAMES) -
            # mesma linha de sempre, so identificada pela classificacao
            # NATIVA e por "marca" (nao por `rotulo`, que pode ser bem
            # diferente do nome usado no dropdown - ex.: WePink tem
            # rotulo "T. We Pink"/"T. WePInk - Cf" - nem por fabricante/
            # marca_f, que podem ainda estar em "Total" se o usuario
            # pulou direto pro dropdown mais fundo, ver update_*_options)
            return {"classificacao": extended[0], "marca": value}
        filters = {"classificacao": default, "rotulo": value}
        if fabricante_f and fabricante_f != "Total":
            filters["fabricante"] = fabricante_f
        if marca_f and marca_f != "Total":
            filters["marca"] = marca_f
        return filters
    if marca_f and marca_f != "Total":
        classificacao = _native_classificacao(marca_f, "Marca")
        filters = {"classificacao": classificacao, "marca": marca_f}
        if fabricante_f and fabricante_f != "Total":
            filters["fabricante"] = fabricante_f
        return filters
    if fabricante_f and fabricante_f != "Total":
        return {"classificacao": "Fabricante", "fabricante": fabricante_f}
    return {"classificacao": "Total", "fabricante": "Total", "marca": "Total", "cod": "1"}


def _breadcrumb(regiao_view, fabricante_f, marca_f, submarca_f, variante_f, subvariante_f):
    parts = [regiao_view]
    for value in (fabricante_f, marca_f, submarca_f, variante_f, subvariante_f):
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


def _embalagem_values(regiao_view, indicator, parent_cod):
    """{nome: {ano: valor}} dos filhos diretos de `parent_cod` ('3' =
    Refil/Nao Refil, '4' = faixas de ml - ver EMBALAGEM_BREAKDOWNS), no
    unico escopo em que essas arvores existem na planilha (Segmento/
    Fabricante/Marca = 'Total'). `categories` vem rankeada pelo ultimo
    ano (maior participacao primeiro), igual discover_top_categories -
    o rotulo de topo/base da pilha ja e recalculado ano a ano dentro do
    grafico (ver alluvial_stack_chart), mas a ordem das LINHAS da
    tabela ao lado segue `categories`; deixar em ordem "natural" do
    Cod. (ex.: faixas de ml crescentes) desalinhava a tabela do
    grafico, que mostra a maior participacao no topo."""
    base_filters = {"regiao": regiao_view, "segmento": "Total", "classificacao": "Total", "fabricante": "Total", "marca": "Total"}
    rows = _children_rows(base_filters, parent_cod)
    if rows.empty:
        return [], {}
    scale = INDICATORS[indicator]["value_scale"]
    values = {
        row.rotulo: {yr: float(getattr(row, f"{indicator}_{yr}")) * scale for yr in YEARS_DEFAULT}
        for row in rows.itertuples()
    }
    last_yr = YEARS_DEFAULT[-1]
    categories = sorted(values, key=lambda cat: values[cat][last_yr], reverse=True)
    return categories, values


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


# classificacao excluida da descida de Marca/Submarca/Variante/Sub
# Variante: cada "Outros X" e o residual de entidades nao rastreadas
# individualmente dentro do nivel anterior (Outros Fabricante = empresas
# nao rastreadas, Outros Marca = submarcas nao rastreadas dentro de uma
# marca, Outros Sub Marca = variantes nao rastreadas dentro de uma
# submarca, Outros Variante = sub variantes nao rastreadas dentro de uma
# variante) - nunca uma entidade de verdade daquele nivel, entao nao
# concorre por uma vaga no ranking (top N) nem aparece como "folha"
# generica quando nao tem detalhe (ver conversa com o usuario)
_EXCLUDE_FROM_RANKING = frozenset({"Outros Fabricante", "Outros Marca", "Outros Sub Marca", "Outros Variante"})

# nomes excluidos do ranking por identidade (nao por classificacao, ver
# _EXCLUDE_FROM_RANKING acima) - "Importados-Cf"/"Importados-Cm" e um
# residual de importados nao rastreados individualmente (classificacao
# "Total", cod raso demais pra entrar no filtro por classificacao), mas
# aparece hoje como "folha" generica em qualquer quebra por Marca/
# Submarca/Variante/Sub Variante (ver conversa com o usuario) - excluido
# explicitamente por nome em vez de classificacao.
EXCLUDE_NAMES_FROM_RANKING = frozenset({"Importados-Cf", "Importados-Cm"})


def build_selection(
    breakdown, regiao_view, segmento_f, fabricante_f, marca_f, submarca_f, variante_f, subvariante_f, indicator_id,
    top_n=_TOP_N, categories_override=None, weight_indicator=None, body_splash_f="Total", fabricante_outros=True,
):
    """Retorna (categories, dimension, filters, values_override, title,
    true_totals) para a combinacao atual de quebra/filtros/regiao.
    `true_totals` e None exceto em Marca/Submarca/Variante (sempre) e
    Fabricante (quando `fabricante_outros=False`), onde e o total real
    (mercado/marca inteiro) usado pra calcular participacao (MS) - o
    grafico so mostra um top N ali, entao a soma das categorias exibidas
    nao e mais o total de verdade. `categories_override`/`weight_indicator`:
    ver `_apply_ranking` - usado por indicadores nao aditivos (ex.: Preco
    Medio) que reaproveitam o ranking de outro indicador em vez de
    rankear por si mesmos. `fabricante_outros`: so vale pra Fabricante -
    inclui (True) ou descarta (False) o bloco sintetico "Demais
    Fabricantes" com o resto do ranking (ver `discover_top_categories`)."""
    if regiao_view == REGIOES_TAB_KEY:
        # aba "Regioes" (ver REGIOES_TAB_KEY): ignora `breakdown` (a UI
        # ja desabilita "Quebra por") - a quebra e sempre a propria
        # regiao - mas os demais filtros continuam livres (ver
        # update_filters_disabled), restringindo o escopo em cada
        # regiao antes de quebrar (ver _regiao_root_values). NAO usa
        # `_breadcrumb` (que omite Segmento de proposito - nas demais
        # views ele e sempre um efeito colateral da quebra, ver
        # SEGMENT_REQUIRED_BREAKDOWNS) porque aqui Segmento e um filtro
        # livre igual aos outros, entao precisa aparecer no titulo pra
        # nao parecer que o filtro nao foi aplicado (ver conversa com o
        # usuario - "Regiões > Feminino" sumindo do titulo).
        crumb_parts = [REGIOES_TAB_KEY]
        for value in (segmento_f, fabricante_f, marca_f, submarca_f, variante_f, subvariante_f):
            if value and value != "Total":
                crumb_parts.append(value)
        crumb = " > ".join(crumb_parts)
        values = _regiao_root_values(
            indicator_id, segmento_f, fabricante_f, marca_f, submarca_f, variante_f, subvariante_f, body_splash_f,
        )
        return REGIOES_BREAKDOWN_CATEGORIES, "regiao", {}, values, crumb, None

    if breakdown in EMBALAGEM_BREAKDOWNS:
        # Segmento/Fabricante/Marca/Submarca/Variante nao existem pra
        # essas duas arvores (ver EMBALAGEM_BREAKDOWNS) - ignora os
        # filtros recebidos (a UI ja os fixa em "Total"/desabilita) e
        # nao usa `_breadcrumb`, que so faria sentido com eles
        parent_cod, label = EMBALAGEM_BREAKDOWNS[breakdown]
        categories, values = _embalagem_values(regiao_view, indicator_id, parent_cod)
        return categories, "rotulo", {}, values, f"{regiao_view} > {label}", None

    crumb = _breadcrumb(regiao_view, fabricante_f, marca_f, submarca_f, variante_f, subvariante_f)

    if breakdown == "segmento":
        if (
            fabricante_f == "Total" and marca_f == "Total" and submarca_f == "Total"
            and variante_f == "Total" and subvariante_f == "Total"
        ):
            # sem nenhum fabricante/marca fixo: usa o ramo cod 6.x (ver
            # _segmento_root_values) em vez do filtro generico, que so
            # enxerga 'segmento'='Total' nesse nivel da arvore
            values = _segmento_root_values(regiao_view, indicator_id)
            return SEGMENTOS, "segmento", {}, values, f"{crumb} > Segmentos", None
        filters = {"regiao": regiao_view, **_scope_filters(fabricante_f, marca_f, submarca_f, variante_f, subvariante_f)}
        return SEGMENTOS, "segmento", filters, None, f"{crumb} > Segmentos", None

    if breakdown == "fabricante":
        base_filters = {"regiao": regiao_view, "segmento": segmento_f}
        parent_cod = _fabricante_root_cod(regiao_view, segmento_f)
        categories, values = discover_top_categories(
            indicator_id, "fabricante", base_filters, parent_cod, other_label="Demais Fabricantes", top_n=top_n,
            categories_override=categories_override, weight_indicator=weight_indicator, add_other=fabricante_outros,
        )
        true_totals = None if fabricante_outros else _cod_own_values(indicator_id, parent_cod, base_filters)
        return categories, "fabricante", base_filters, values, f"{crumb} > Fabricantes (top {top_n})", true_totals

    # Marca/Submarca/Variante: nao exigem fabricante/marca/submarca fixo -
    # com o pai em "Total", descobre a partir da raiz (todos os
    # fabricantes) e desce ate o nivel pedido (ver _descend_to_level)
    base_filters = {"regiao": regiao_view, "segmento": segmento_f}

    if breakdown == BODY_SPLASH_BREAKDOWN_KEY:
        # mesma cascata de start_cod da quebra "subvariante" (a mais
        # profunda): Fabricante/Marca/Submarca/Variante/Sub Variante,
        # qualquer um deles fixo, restringe o escopo antes da descida -
        # ver update_filters_disabled, que mantem a cadeia inteira
        # habilitada como filtro pra essa quebra (igual a Segmento).
        if subvariante_f and subvariante_f != "Total":
            start_cod = _self_cod(regiao_view, segmento_f, "Sub Variante", marca=marca_f, rotulo=subvariante_f)
        elif variante_f and variante_f != "Total":
            start_cod = _self_cod(regiao_view, segmento_f, "Variante", marca=marca_f, rotulo=variante_f)
        elif submarca_f and submarca_f != "Total":
            start_cod = _self_cod(regiao_view, segmento_f, "Sub Marca", marca=marca_f, rotulo=submarca_f)
        elif marca_f and marca_f != "Total":
            start_cod = _self_cod(regiao_view, segmento_f, "Marca", fabricante=fabricante_f, marca=marca_f)
        elif fabricante_f and fabricante_f != "Total":
            start_cod = _self_cod(regiao_view, segmento_f, "Fabricante", fabricante=fabricante_f)
        else:
            start_cod = _fabricante_root_cod(regiao_view, segmento_f)
        values = _body_splash_values(indicator_id, base_filters, start_cod)
        return [_BODY_SPLASH_LABEL, _NOT_BODY_SPLASH_LABEL], "rotulo", {}, values, f"{crumb} > Body Splash", None

    if breakdown == "marca":
        if fabricante_f and fabricante_f != "Total":
            start_cod = _self_cod(regiao_view, segmento_f, "Fabricante", fabricante=fabricante_f)
        else:
            start_cod = _fabricante_root_cod(regiao_view, segmento_f)
        values_all = _descend_to_level(indicator_id, "marca", base_filters, start_cod, {"Marca"}, _EXCLUDE_FROM_RANKING)
        weight_all = (
            _descend_to_level(weight_indicator, "marca", base_filters, start_cod, {"Marca"}, _EXCLUDE_FROM_RANKING)
            if weight_indicator else None
        )
        # add_other=False (sem bucket sintetico "Outras"/"Demais outras")
        # + true_totals real: mesmo tratamento de Submarca/Variante (ver
        # abaixo) - o top N exibido e so um recorte, nao fecha o total
        # sozinho, entao o grafico troca o rotulo de total/variacao por
        # "Top N = X% do total" (ver _build_blocks)
        categories, values = _apply_ranking(
            values_all, top_n, add_other=False, categories_override=categories_override, weight_all=weight_all,
        )
        true_totals = _cod_own_values(indicator_id, start_cod, base_filters)
        return categories, "marca", base_filters, values, f"{crumb} > Marcas (top {top_n})", true_totals

    if breakdown == "submarca":
        if marca_f and marca_f != "Total":
            start_cod = _self_cod(regiao_view, segmento_f, "Marca", fabricante=fabricante_f, marca=marca_f)
        elif fabricante_f and fabricante_f != "Total":
            start_cod = _self_cod(regiao_view, segmento_f, "Fabricante", fabricante=fabricante_f)
        else:
            start_cod = _fabricante_root_cod(regiao_view, segmento_f)
        values_all = _descend_to_level(indicator_id, "rotulo", base_filters, start_cod, {"Sub Marca"}, _EXCLUDE_FROM_RANKING, body_splash_f)
        weight_all = (
            _descend_to_level(weight_indicator, "rotulo", base_filters, start_cod, {"Sub Marca"}, _EXCLUDE_FROM_RANKING, body_splash_f)
            if weight_indicator else None
        )
        categories, values = _apply_ranking(
            values_all, top_n, add_other=False, categories_override=categories_override, weight_all=weight_all,
        )
        true_totals = _cod_own_values(indicator_id, start_cod, base_filters)
        return categories, "rotulo", base_filters, values, f"{crumb} > Submarcas (top {top_n})", true_totals

    if breakdown == "variante":
        if submarca_f and submarca_f != "Total":
            start_cod = _self_cod(regiao_view, segmento_f, "Sub Marca", marca=marca_f, rotulo=submarca_f)
        elif marca_f and marca_f != "Total":
            start_cod = _self_cod(regiao_view, segmento_f, "Marca", fabricante=fabricante_f, marca=marca_f)
        elif fabricante_f and fabricante_f != "Total":
            start_cod = _self_cod(regiao_view, segmento_f, "Fabricante", fabricante=fabricante_f)
        else:
            start_cod = _fabricante_root_cod(regiao_view, segmento_f)
        values_all = _descend_to_level(indicator_id, "rotulo", base_filters, start_cod, {"Variante"}, _EXCLUDE_FROM_RANKING, body_splash_f)
        weight_all = (
            _descend_to_level(weight_indicator, "rotulo", base_filters, start_cod, {"Variante"}, _EXCLUDE_FROM_RANKING, body_splash_f)
            if weight_indicator else None
        )
        categories, values = _apply_ranking(
            values_all, top_n, add_other=False, categories_override=categories_override, weight_all=weight_all,
        )
        true_totals = _cod_own_values(indicator_id, start_cod, base_filters)
        return categories, "rotulo", base_filters, values, f"{crumb} > Variantes (top {top_n})", true_totals

    # breakdown == "subvariante" - so existe pra 2 marcas na planilha
    # (Natura, Boticario); as demais retornam categorias vazias (ver
    # "Sem dados para esta combinacao de filtros" na tela)
    if variante_f and variante_f != "Total":
        start_cod = _self_cod(regiao_view, segmento_f, "Variante", marca=marca_f, rotulo=variante_f)
    elif submarca_f and submarca_f != "Total":
        start_cod = _self_cod(regiao_view, segmento_f, "Sub Marca", marca=marca_f, rotulo=submarca_f)
    elif marca_f and marca_f != "Total":
        start_cod = _self_cod(regiao_view, segmento_f, "Marca", fabricante=fabricante_f, marca=marca_f)
    elif fabricante_f and fabricante_f != "Total":
        start_cod = _self_cod(regiao_view, segmento_f, "Fabricante", fabricante=fabricante_f)
    else:
        start_cod = _fabricante_root_cod(regiao_view, segmento_f)
    values_all = _descend_to_level(indicator_id, "rotulo", base_filters, start_cod, {"Sub Variante"}, _EXCLUDE_FROM_RANKING, body_splash_f)
    weight_all = (
        _descend_to_level(weight_indicator, "rotulo", base_filters, start_cod, {"Sub Variante"}, _EXCLUDE_FROM_RANKING, body_splash_f)
        if weight_indicator else None
    )
    categories, values = _apply_ranking(
        values_all, top_n, add_other=False, categories_override=categories_override, weight_all=weight_all,
    )
    true_totals = _cod_own_values(indicator_id, start_cod, base_filters)
    return categories, "rotulo", base_filters, values, f"{crumb} > Sub Variantes (top {top_n})", true_totals


def _dropdown(id_, options, value, disabled=False):
    return dcc.Dropdown(id=id_, options=[{"label": o, "value": o} for o in options], value=value, clearable=False, disabled=disabled)


def _pptx_button(id_):
    return html.Button(
        [
            html.Img(
                src=app.get_asset_url("pptx_icon.svg"),
                style={"height": "14px", "width": "14px", "marginRight": "6px"},
            ),
            "Exportar PowerPoint",
        ],
        id=id_,
        n_clicks=0,
        style={
            "fontSize": "12.5px", "padding": "5px 10px", "cursor": "pointer",
            "border": "1px solid #ccc", "borderRadius": "4px", "background": "white",
            "display": "inline-flex", "alignItems": "center",
        },
    )


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
        style={"borderCollapse": "collapse", "width": "100%", "fontSize": "15px"},
    )


def _additions_cell(value, value_decimals):
    color = _NOMINAL_COLOR if value == 0 else (_POSITIVE_COLOR if value >= 0 else _NEGATIVE_COLOR)
    text = f"{value:,.{value_decimals}f}" if value == 0 else f"{value:+,.{value_decimals}f}"
    return html.Td(text, style={**_TABLE_CELL_STYLE, "color": color, "fontVariantNumeric": "tabular-nums"})


def _additions_table(names, deltas, value_decimals):
    """Tabela simples (sem % de variacao/participacao, ao contrario de
    `_variation_table`) pra uma aba "Adicoes de X" (ver ADDITIONS_TABS):
    UMA coluna so, "AnoAnterior→UltimoAno" (ex.: "2024→2025" - a mesma,
    unica transicao do grafico, ver ADDITIONS_YEAR0/YEAR1), mostrando
    exatamente o numero plotado no grafico pra cada nome - "reflete o
    que se ve no grafico", nao uma tabela de variacao percentual."""
    if not names:
        return html.P("Sem dados para esta combinação de filtros.", style={"color": "#888", "fontSize": "12px"})

    header = html.Tr(
        [
            html.Th("Categoria", style={**_TABLE_CELL_STYLE, "textAlign": "left"}),
            html.Th(f"{ADDITIONS_YEAR0[1:]}→{ADDITIONS_YEAR1[1:]}", style=_TABLE_CELL_STYLE),
        ]
    )
    rows = [
        html.Tr(
            [
                html.Td(name, style={**_TABLE_CELL_STYLE, "textAlign": "left", "fontWeight": "600", "whiteSpace": "normal"}),
                _additions_cell(deltas[name], value_decimals),
            ]
        )
        for name in names
    ]
    return html.Table(
        [html.Thead(header), html.Tbody(rows)],
        style={"borderCollapse": "collapse", "width": "100%", "fontSize": "15px"},
    )


def _additions_panel(cfg):
    """Layout de uma aba "Adicoes de X" (ver ADDITIONS_TABS): grafico
    waterfall NAO responsivo (largura cresce com o numero de blocos -
    ate 30 categorias x 4 transicoes, ver charts.unit_additions_bridge_chart)
    - scroll horizontal em vez de espremer tudo num container de largura
    fixa - com tabela e highlight embaixo do grafico (nao do lado, como
    os outros blocos), ja que com ate 30+1 linhas (top N + "Outras") o
    grafico ja precisa de toda a largura disponivel."""
    return [
        html.Div(
            style={"display": "flex", "justifyContent": "flex-end", "marginBottom": "12px"},
            children=[
                _pptx_button(f"export-btn-{cfg['key']}"),
                dcc.Download(id=f"download-{cfg['key']}"),
            ],
        ),
        html.Div(
            style={"overflowX": "auto", "marginBottom": "24px"},
            children=[
                dcc.Graph(
                    id=cfg["graph_id"],
                    config={"responsive": False, "displayModeBar": False},
                ),
            ],
        ),
        html.Div(
            style={"display": "flex", "gap": "20px", "flexWrap": "wrap", "alignItems": "flex-start"},
            children=[
                html.Div(id=cfg["table_id"], style={"flex": "3", "minWidth": "420px"}),
                html.Div(
                    [
                        html.B("Highlights"),
                        html.P(
                            id=cfg["insight_id"],
                            style={"margin": "4px 0 0", "fontSize": "15.5px", "lineHeight": "1.5", "color": "#333"},
                        ),
                    ],
                    style={"flex": "1", "minWidth": "260px", "maxWidth": "360px"},
                ),
            ],
        ),
    ]


def _chart_block(key):
    legend_text = TABLE_LEGEND_WITH_SHARE if INDICATORS[key]["additive"] else TABLE_LEGEND_NO_SHARE
    return html.Div(
        style={"marginBottom": "40px"},
        children=[
            html.Div(
                style={"display": "flex", "justifyContent": "flex-end", "marginBottom": "4px"},
                children=[
                    _pptx_button(f"export-btn-{key}"),
                    dcc.Download(id=f"download-{key}"),
                ],
            ),
            html.Div(
                style={"display": "flex", "gap": "20px", "flexWrap": "wrap", "alignItems": "flex-start"},
                children=[
                    dcc.Graph(
                        id=f"graph-{key}",
                        config={"responsive": True, "displayModeBar": False},
                        style={"flex": "5", "minWidth": "420px"},
                    ),
                    html.Div(
                        style={"flex": "4", "minWidth": "420px"},
                        children=[
                            html.Div(id=f"variation-table-{key}", style={"paddingTop": "60px"}),
                            html.P(legend_text, style={"margin": "6px 0 0", "fontSize": "11px", "lineHeight": "1.4", "color": "#888"}),
                        ],
                    ),
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


_CONS_TH_STYLE = {"textAlign": "left", "padding": "6px 12px", "borderBottom": "2px solid #ddd", "fontSize": "13px", "color": "#666"}
_CONS_TD_STYLE = {"padding": "6px 12px", "borderBottom": "1px solid #eee", "fontSize": "14px"}


def _considerations_reclass_table():
    """Tabela De -> Para das reclassificacoes (ver CATEGORY_CHANGES/
    etl.load_category_exceptions, coluna "Classificação_nova") - gerada
    direto do arquivo de excecoes, entao cresce sozinha conforme
    fonte/change_category.xlsx ganha novas linhas, sem precisar editar
    esta pagina."""
    if not CATEGORY_CHANGES:
        return html.P("Nenhuma reclassificação registrada.", style={"color": "#666"})
    return html.Table(
        style={"borderCollapse": "collapse", "width": "100%", "marginBottom": "8px"},
        children=[
            html.Thead(html.Tr([
                html.Th("Produto", style=_CONS_TH_STYLE),
                html.Th("Cód.", style=_CONS_TH_STYLE),
                html.Th("De", style=_CONS_TH_STYLE),
                html.Th("Para", style=_CONS_TH_STYLE),
                html.Th("Ignorado?", style=_CONS_TH_STYLE),
            ])),
            html.Tbody([
                html.Tr([
                    html.Td(change["nome"], style=_CONS_TD_STYLE),
                    html.Td(change["cod"], style={**_CONS_TD_STYLE, "color": "#888", "fontFamily": "monospace"}),
                    html.Td(change["de"], style=_CONS_TD_STYLE),
                    html.Td(f"→ {change['para']}", style={**_CONS_TD_STYLE, "fontWeight": "600"}),
                    html.Td(
                        "Sim — nunca vira categoria própria" if change["cod"] in IGNORE_CODS else "—",
                        style={**_CONS_TD_STYLE, "color": "#C23B3B", "fontWeight": "600"} if change["cod"] in IGNORE_CODS
                        else {**_CONS_TD_STYLE, "color": "#bbb"},
                    ),
                ])
                for change in CATEGORY_CHANGES
            ]),
        ],
    )


def _considerations_extend_list():
    """Lista das entidades "sem filhos" (ver EXTENDED_NAMES/
    ExtendCategory) selecionaveis como filtro em niveis extras."""
    if not EXTENDED_NAMES:
        return html.P("Nenhuma extensão registrada.", style={"color": "#666"})
    return html.Ul(
        style={"marginTop": "8px"},
        children=[
            html.Li(f"{name} — também selecionável como {', '.join(sorted(labels))}", style={"marginBottom": "4px"})
            for name, (native, labels) in sorted(EXTENDED_NAMES.items())
        ],
    )


def _considerations_body_splash_table():
    """Tabela Marca/Submarca/Body Splash (ver etl.load_body_splash,
    fonte/body_splash.xlsx) - so linhas de Submarca de verdade tem essa
    classificacao confiavel (ver BODY_SPLASH_BREAKDOWNS/comentario em
    update_filters_disabled), por isso a tabela filtra so classificacao
    == "Sub Marca". Lista as 115 submarcas classificadas por inteiro,
    "Sim" primeiro (destacado em verde) pra ressaltar quais sao Body
    Splash - so 10 das 115, a maioria e "Não"."""
    sub = df.loc[df["classificacao"] == "Sub Marca", ["marca", "rotulo", "is_body_splash"]].drop_duplicates()
    if sub.empty:
        return html.P("Nenhuma submarca classificada.", style={"color": "#666"})
    ordered = sub.sort_values(["is_body_splash", "marca", "rotulo"], ascending=[False, True, True])
    n_sim = (sub["is_body_splash"] == "Sim").sum()
    rows = [
        html.Tr([
            html.Td(marca, style=_CONS_TD_STYLE),
            html.Td(rotulo, style=_CONS_TD_STYLE),
            html.Td(
                is_bs,
                style={**_CONS_TD_STYLE, "fontWeight": "600", "color": "#1E8E5A"} if is_bs == "Sim" else _CONS_TD_STYLE,
            ),
        ])
        for marca, rotulo, is_bs in ordered.itertuples(index=False)
    ]
    return html.Div([
        html.Table(
            style={"borderCollapse": "collapse", "width": "100%", "marginBottom": "8px"},
            children=[
                html.Thead(html.Tr([
                    html.Th("Marca", style=_CONS_TH_STYLE),
                    html.Th("Submarca", style=_CONS_TH_STYLE),
                    html.Th("Body Splash", style=_CONS_TH_STYLE),
                ])),
                html.Tbody(rows),
            ],
        ),
        html.P(
            f"{n_sim} de {len(sub)} submarcas classificadas são Body Splash.",
            style={"color": "#888", "fontSize": "13px", "marginTop": "4px"},
        ),
    ])


_CONSIDERATIONS_STYLE = {
    "fontFamily": "'Roboto', -apple-system, Helvetica, Arial, sans-serif",
    "maxWidth": "900px", "margin": "0 auto", "padding": "24px",
}


def _considerations_layout():
    """Pagina "Considerações": resumo das reclassificacoes manuais feitas
    em fonte/change_category.xlsx (ver etl.load_category_exceptions),
    pra quem olha os numeros do dashboard entender rapido o que mudou em
    relacao a planilha original, sem precisar ler o codigo."""
    return html.Div(
        id="considerations-view",
        style={**_CONSIDERATIONS_STYLE, "display": "none"},
        children=[
            html.Div(
                style={"display": "flex", "alignItems": "center", "gap": "12px", "marginBottom": "20px"},
                children=[
                    html.Img(src=app.get_asset_url("symrise_logo.png"), style={"height": "30px"}),
                    html.H2("Considerações", style={"margin": 0, "flex": "1"}),
                    html.Button(
                        "← Voltar ao dashboard",
                        id="considerations-close-btn",
                        n_clicks=0,
                        style={
                            "fontSize": "13px", "padding": "6px 12px", "cursor": "pointer",
                            "border": "1px solid #ccc", "borderRadius": "4px", "background": "white", "color": "#333",
                        },
                    ),
                ],
            ),
            html.P(
                "Alguns produtos vinham classificados num nível diferente do "
                "real na planilha fonte. Esta página resume os ajustes manuais "
                "feitos (ver fonte/change_category.xlsx) para que os números do "
                "dashboard reflitam a hierarquia correta.",
                style={"color": "#444", "lineHeight": "1.6", "marginBottom": "24px"},
            ),
            html.H4("Reclassificações"),
            html.P(
                "O Cód. (posição na árvore) não muda — só o nível considerado "
                "na quebra/gráfico. Um produto marcado como \"Ignorado\" (ex.: "
                "Ekos-Cf, T. Egeo Choc-Cf) nunca aparece como categoria "
                "própria em nenhuma quebra — seus filhos passam a aparecer "
                "um nível acima, direto dentro do pai dele (ex.: família "
                "Ekos, dentro de Natura).",
                style={"color": "#666", "fontSize": "13.5px", "lineHeight": "1.5", "marginBottom": "8px"},
            ),
            _considerations_reclass_table(),
            html.H4("Excluídos do ranking (top N)", style={"marginTop": "28px"}),
            html.P(
                "Buckets residuais (nunca uma entidade de verdade daquele "
                "nível) não concorrem por uma vaga no top 10/20/30 das "
                "quebras por Marca, Submarca e Variante:",
                style={"color": "#666", "fontSize": "13.5px", "lineHeight": "1.5", "marginBottom": "8px"},
            ),
            html.Ul(
                style={"marginTop": "4px"},
                children=[
                    html.Li(name, style={"marginBottom": "4px"})
                    for name in sorted(_EXCLUDE_FROM_RANKING | EXCLUDE_NAMES_FROM_RANKING)
                ],
            ),
            html.H4("Body Splash", style={"marginTop": "28px"}),
            html.P(
                "Classificação manual (ver fonte/body_splash.xlsx) de quais "
                "submarcas são consideradas Body Splash — usada pelo filtro "
                "IsBodySplash e pela quebra \"Body Splash\" (só confiável a "
                "partir do nível Submarca).",
                style={"color": "#666", "fontSize": "13.5px", "lineHeight": "1.5", "marginBottom": "8px"},
            ),
            _considerations_body_splash_table(),
            html.H4("Selecionáveis em níveis extras", style={"marginTop": "28px"}),
            html.P(
                "Marcas/fabricantes sem detalhamento na planilha (não têm "
                "submarca/variante) que passaram a também aparecer nos "
                "dropdowns de filtro nesses níveis mais fundos — e só até "
                "eles, não aparecem em nenhum nível além do listado.",
                style={"color": "#666", "fontSize": "13.5px", "lineHeight": "1.5"},
            ),
            _considerations_extend_list(),
        ],
    )


_MAIN_DASHBOARD_STYLE = {"fontFamily": "'Roboto', -apple-system, Helvetica, Arial, sans-serif", "maxWidth": "1400px", "margin": "0 auto", "padding": "24px"}

app.layout = html.Div(
    children=[
        html.Div(
    id="main-dashboard-view",
    style=_MAIN_DASHBOARD_STYLE,
    children=[
        html.Div(
            style={"display": "flex", "alignItems": "center", "gap": "12px", "marginBottom": "8px"},
            children=[
                html.Img(src=app.get_asset_url("symrise_logo.png"), style={"height": "30px"}),
                html.H2("Kantar Worldpanel - Dashboard", style={"margin": 0, "flex": "1"}),
                html.Button(
                    "Considerações",
                    id="considerations-open-btn",
                    n_clicks=0,
                    style={
                        "fontSize": "13px", "padding": "6px 12px", "cursor": "pointer",
                        "border": "1px solid #ccc", "borderRadius": "4px", "background": "white", "color": "#333",
                    },
                ),
            ],
        ),
        dcc.Tabs(
            id="regiao-tabs",
            value=REGIAO_VIEWS[0],
            children=(
                [dcc.Tab(label=r, value=r) for r in REGIAO_VIEWS]
                + [dcc.Tab(label=REGIOES_TAB_KEY, value=REGIOES_TAB_KEY)]
            ),
        ),
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
                        {"label": "Sub Variante", "value": "subvariante"},
                        {"label": "Body Splash", "value": BODY_SPLASH_BREAKDOWN_KEY},
                        {"label": "Embalagem (Tipo)", "value": "embalagem_tipo"},
                        {"label": "Embalagem (Conteúdo)", "value": "embalagem_conteudo"},
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
                html.Div(
                    style={"display": "flex", "alignItems": "center", "gap": "28px", "flexWrap": "wrap"},
                    children=[
                        html.Div([
                            html.Label("Ranking (top N por indicador, base 2025)"),
                            dcc.RadioItems(
                                id="top-n-selector",
                                options=[{"label": f"Top {n}", "value": n} for n in TOP_N_OPTIONS],
                                value=TOP_N_DEFAULT,
                                inline=True,
                                inputStyle={"marginRight": "4px", "marginLeft": "12px"},
                            ),
                        ]),
                        # so aparece pra quebra Fabricante (ver
                        # update_top_n_visibility) - controla se o bloco
                        # sintetico "Demais Fabricantes" (resto do top N)
                        # entra ou nao na pilha (ver build_selection)
                        dcc.Checklist(
                            id="fabricante-outros-checkbox",
                            options=[{"label": 'Incluir bloco "Demais Fabricantes"', "value": "incluir"}],
                            value=["incluir"],
                            style={"display": "none"},
                            inputStyle={"marginRight": "6px"},
                        ),
                    ],
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
                html.Div([html.Label("Sub Variante"), _dropdown("subvariante-filter", ["Total"] + ALL_SUBVARIANTES, "Total")], style={"flex": "1", "minWidth": "160px"}),
                html.Div([html.Label("IsBodySplash"), _dropdown("body-splash-filter", BODY_SPLASH_OPTIONS, "Total")], style={"flex": "1", "minWidth": "160px"}),
            ],
        ),
        dcc.Tabs(
            id="indicator-tabs",
            value=INDICATOR_BLOCKS[0],
            children=(
                [dcc.Tab(label=INDICATORS[key]["label"], value=key) for key in INDICATOR_BLOCKS]
                + [dcc.Tab(label=PRICE_UNIT_TAB_LABEL, value=PRICE_UNIT_TAB_KEY)]
                + [dcc.Tab(label=cfg["tab_label"], value=cfg["key"]) for cfg in ADDITIONS_TABS]
            ),
            style={"marginBottom": "16px"},
        ),
        dcc.Loading(
            type="circle",
            fullscreen=True,
            # escuro (nao branco): um overlay branco translucido sobre o
            # fundo branco do dashboard quase some o conteudo, dando a
            # impressao de pagina em branco/quebrada - escuro cria
            # contraste visivel e fica claro que e so um dimmer, com o
            # dashboard ainda perceptivel por baixo
            overlay_style={"visibility": "visible", "opacity": 0.5, "backgroundColor": "#1a1a1a"},
            children=html.Div(
                children=[
                    html.Div(
                        id=f"indicator-panel-{key}",
                        style={"display": "block" if key == INDICATOR_BLOCKS[0] else "none"},
                        children=_chart_block(key),
                    )
                    for key in INDICATOR_BLOCKS
                ]
                + [
                    html.Div(
                        id=f"indicator-panel-{PRICE_UNIT_TAB_KEY}",
                        style={"display": "none"},
                        children=[
                            html.Div(
                                style={"display": "flex", "justifyContent": "flex-end", "marginBottom": "12px"},
                                children=[
                                    _pptx_button("export-btn-price-unit"),
                                    dcc.Download(id="download-price-unit"),
                                ],
                            ),
                            html.Div(
                                id="waterfall-container",
                                style={"display": "flex", "flexDirection": "column", "gap": "16px"},
                            ),
                        ],
                    )
                ]
                + [
                    html.Div(
                        id=f"indicator-panel-{cfg['key']}",
                        style={"display": "none"},
                        children=_additions_panel(cfg),
                    )
                    for cfg in ADDITIONS_TABS
                ]
            ),
        ),
    ],
        ),
        _considerations_layout(),
    ],
)


@app.callback(
    Output("main-dashboard-view", "style"),
    Output("considerations-view", "style"),
    Input("considerations-open-btn", "n_clicks"),
    Input("considerations-close-btn", "n_clicks"),
)
def _toggle_considerations(_open_clicks, _close_clicks):
    # dispara pelo Input que mudou por ultimo (ver dash.ctx) - simples
    # toggle de visibilidade entre as duas "paginas" (ver
    # _considerations_layout), sem precisar de roteamento por URL real.
    # Preserva o resto do style (fontFamily/maxWidth/...) de
    # _MAIN_DASHBOARD_STYLE - so troca "display", nao substitui o dict
    # inteiro.
    triggered = ctx.triggered_id
    if triggered == "considerations-open-btn":
        return {**_MAIN_DASHBOARD_STYLE, "display": "none"}, {**_CONSIDERATIONS_STYLE, "display": "block"}
    return {**_MAIN_DASHBOARD_STYLE, "display": "block"}, {**_CONSIDERATIONS_STYLE, "display": "none"}


_ALL_TAB_KEYS = INDICATOR_BLOCKS + [PRICE_UNIT_TAB_KEY] + [cfg["key"] for cfg in ADDITIONS_TABS]


@app.callback(
    [Output(f"indicator-panel-{key}", "style") for key in _ALL_TAB_KEYS],
    Input("indicator-tabs", "value"),
)
def update_indicator_tabs(active_key):
    # todos os blocos continuam sendo calculados/atualizados normalmente
    # pelo update_charts/update_waterfall (Input de filtro nao muda) - so
    # a visibilidade troca, entao alternar de aba e instantaneo, sem
    # precisar recarregar
    return [{"display": "block"} if key == active_key else {"display": "none"} for key in _ALL_TAB_KEYS]


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
    Output("subvariante-filter", "options"),
    Output("subvariante-filter", "value"),
    Input("marca-filter", "value"),
)
def update_subvariante_options(marca_f):
    # mesmo flatten-por-marca de update_submarca_options/
    # update_variante_options (nao filtra tambem por Variante/Submarca
    # selecionados) - so tem opcoes reais pra Natura/Boticario
    subvariantes = ALL_SUBVARIANTES if marca_f == "Total" else SUBVARIANTE_BY_MARCA.get(marca_f, [])
    return [{"label": o, "value": o} for o in (["Total"] + subvariantes)], "Total"


# Dividido em 2 callbacks pra evitar dependencia circular: este aqui
# reage a mudancas em Submarca/Variante/Sub Variante (pra reforcar
# Segmento real assim que um deles for fixado na aba "Regioes" - ver
# abaixo), mas NAO pode ser o mesmo callback que forca Fabricante de
# volta pra "Total" (proximo, `update_chain_filters_disabled`): esse
# outro Output alimenta Marca (update_marca_options) -> Submarca
# (update_submarca_options), e Submarca como Input aqui fecharia um
# ciclo Fabricante -> Marca -> Submarca -> este callback -> Fabricante.
@app.callback(
    Output("dimension-dropdown", "disabled"),
    Output("segmento-filter", "disabled"),
    Output("segmento-filter", "options"),
    Output("segmento-filter", "value"),
    Output("body-splash-filter", "disabled"),
    Output("body-splash-filter", "value"),
    Input("dimension-dropdown", "value"),
    Input("regiao-tabs", "value"),
    Input("submarca-filter", "value"),
    Input("variante-filter", "value"),
    Input("subvariante-filter", "value"),
    State("segmento-filter", "value"),
    State("body-splash-filter", "value"),
)
def update_segmento_and_bodysplash(breakdown, regiao_view, submarca_f, variante_f, subvariante_f, segmento_f, body_splash_f):
    # Segmento e um eixo independente da cadeia Fabricante>Marca>Submarca>
    # Variante: so fica desabilitado quando ele proprio e a quebra.
    # Embalagem (Tipo/Conteudo) so combina com Regiao (ver
    # EMBALAGEM_BREAKDOWNS): desabilita Segmento tambem, sem excecao.
    # Aba "Regioes" (ver REGIOES_TAB_KEY) so desabilita "Quebra por" (nao
    # ha quebra por Segmento/Fabricante/etc ali, so por regiao) -
    # Segmento fica livre como mais um filtro (ver
    # _regiao_root_values/_selection_start_cod).
    is_regioes = regiao_view == REGIOES_TAB_KEY
    is_embalagem = breakdown in EMBALAGEM_BREAKDOWNS

    # Marca/Submarca/Variante/Sub Variante nao existem no agregador
    # Segmento="Total" - a planilha so as detalha dentro de Feminino/
    # Masculino/Infantil/Unisex (Submarca/Variante/Sub Variante nao tem
    # nenhuma linha em "Total"; Marca ate tem algumas, mas misturadas
    # com totais de fabricante reaproveitados como "marca" pela descida
    # generica - nao e uma quebra confiavel) - por isso tira "Total" das
    # opcoes e forca um segmento real. Body Splash tem a mesma restricao
    # (is_body_splash so existe em linhas de Submarca/Variante/Sub
    # Variante, ausentes em Segmento="Total" - ver SEGMENT_REQUIRED_BREAKDOWNS).
    # Regioes so entra nessa restricao quando o proprio FILTRO (nao a
    # quebra, que nao existe ali) desce ate Submarca/Variante/Sub
    # Variante - Marca/Fabricante fixos continuam OK com Segmento="Total"
    # (ver _selection_start_cod, validado contra o true_totals das
    # quebras normais); a mesma condicao tambem libera IsBodySplash.
    if is_regioes:
        regioes_deep_filter = (
            (submarca_f and submarca_f != "Total") or (variante_f and variante_f != "Total")
            or (subvariante_f and subvariante_f != "Total")
        )
        if regioes_deep_filter:
            segmento_options = SEGMENTOS
            segmento_value = segmento_f if segmento_f != "Total" else SEGMENTOS[0]
        else:
            segmento_options = SEGMENTO_FILTER_OPTIONS
            segmento_value = segmento_f
        body_splash_enabled = regioes_deep_filter
    elif breakdown in SEGMENT_REQUIRED_BREAKDOWNS:
        segmento_options = SEGMENTOS
        segmento_value = segmento_f if segmento_f != "Total" else SEGMENTOS[0]
        body_splash_enabled = breakdown in BODY_SPLASH_BREAKDOWNS
    elif is_embalagem:
        segmento_options = SEGMENTO_FILTER_OPTIONS
        segmento_value = "Total"
        body_splash_enabled = False
    elif breakdown == "segmento":
        # a propria quebra: fixar um segmento especifico aqui seria
        # contraditorio (a quebra ja mostra os 4 segmentos como
        # categorias separadas) - volta pra "Total" em vez de deixar o
        # ultimo valor usado (ex.: "Feminino" de uma quebra anterior
        # por Marca) parado ali, desabilitado - isso parecia uma trava
        # especifica naquele segmento pro usuario, quando na verdade o
        # filtro so nao se aplica nessa quebra (ver conversa com o
        # usuario, print de "Feminino" travado ao voltar pra Segmento).
        segmento_options = SEGMENTO_FILTER_OPTIONS
        segmento_value = "Total"
        body_splash_enabled = False
    else:
        segmento_options = SEGMENTO_FILTER_OPTIONS
        segmento_value = segmento_f
        body_splash_enabled = False

    segmento_enabled = is_regioes or ((not is_embalagem) and breakdown != "segmento")
    body_splash_value = body_splash_f if body_splash_enabled else "Total"

    return (
        is_regioes,
        not segmento_enabled,
        [{"label": o, "value": o} for o in segmento_options],
        segmento_value,
        not body_splash_enabled,
        body_splash_value,
    )


@app.callback(
    Output("fabricante-filter", "disabled"),
    Output("fabricante-filter", "value"),
    Output("marca-filter", "disabled"),
    Output("submarca-filter", "disabled"),
    Output("variante-filter", "disabled"),
    Output("subvariante-filter", "disabled"),
    Input("dimension-dropdown", "value"),
    Input("regiao-tabs", "value"),
    State("fabricante-filter", "value"),
)
def update_chain_filters_disabled(breakdown, regiao_view, fabricante_f):
    # Dentro da cadeia Fabricante>Marca>Submarca>Variante>Sub Variante,
    # um filtro fica disponivel se for mais raso que a quebra ativa
    # (ancestral dela) ou se a quebra for Segmento OU Body Splash (a
    # cadeia toda vira filtro nos dois casos - Body Splash desce ate onde
    # o filtro fixar, ver build_selection); a propria quebra e os niveis
    # mais fundos ficam desabilitados (nao faz sentido fixar Submarca
    # enquanto quebra por Marca, por exemplo). Embalagem (Tipo/Conteudo)
    # desabilita a cadeia inteira, sem excecao. Aba "Regioes" (ver
    # REGIOES_TAB_KEY) libera a cadeia inteira como filtro (mesmo
    # tratamento de quebra=="segmento" - ver update_segmento_and_bodysplash
    # pro forcamento de Segmento quando Submarca/Variante/Sub Variante
    # estiver fixo).
    is_regioes = regiao_view == REGIOES_TAB_KEY
    is_embalagem = breakdown in EMBALAGEM_BREAKDOWNS

    def enabled(name):
        if is_regioes:
            return True
        if is_embalagem:
            return False
        if breakdown in ("segmento", BODY_SPLASH_BREAKDOWN_KEY):
            return True
        if breakdown == name:
            return False
        return FILTER_DEPTH[name] < FILTER_DEPTH[breakdown]

    # forca Fabricante de volta pra "Total" so ao entrar em Embalagem - o
    # proprio valor "congelado" (filtro desabilitado) seria enganoso no
    # breadcrumb/insight, sugerindo um recorte que a quebra ignora por
    # completo. Regioes nao reseta (o filtro continua habilitado/util
    # ali). O reset cascateia sozinho pra Marca/Submarca/Variante/Sub
    # Variante via update_marca_options/update_submarca_options/
    # update_variante_options/update_subvariante_options (ja escutam
    # mudanca de Fabricante/Marca), sem precisar de mais Outputs aqui
    # (evitaria erro de "duplicate callback output").
    fabricante_value = "Total" if is_embalagem else fabricante_f

    return (
        not enabled("fabricante"),
        fabricante_value,
        not enabled("marca"),
        not enabled("submarca"),
        not enabled("variante"),
        not enabled("subvariante"),
    )


@app.callback(
    Output("top-n-container", "style"),
    Output("top-n-selector", "options"),
    Output("top-n-selector", "value"),
    Output("fabricante-outros-checkbox", "style"),
    Input("dimension-dropdown", "value"),
    Input("regiao-tabs", "value"),
    State("top-n-selector", "value"),
)
def update_top_n_visibility(breakdown, regiao_view, current_top_n):
    """Fabricante usa opcoes de ranking proprias (FABRICANTE_TOP_N_OPTIONS)
    e mostra o checkbox "Demais Fabricantes"; Marca/Submarca/Variante/Sub
    Variante usam TOP_N_OPTIONS, sem o checkbox. Preserva o valor atual do
    seletor quando ele continua valido no novo conjunto de opcoes (ex.:
    10 existe nos dois) - so cai pro default do grupo quando nao (ex.: 20
    ao trocar pra Fabricante). Aba "Regioes" (ver REGIOES_TAB_KEY) nunca
    mostra o seletor - nao ha ranking, sao sempre as 4 regioes reais."""
    container_style = {"margin": "0 0 16px"}
    if breakdown not in RANKED_BREAKDOWNS or regiao_view == REGIOES_TAB_KEY:
        container_style["display"] = "none"

    if breakdown == "fabricante":
        options, default = FABRICANTE_TOP_N_OPTIONS, FABRICANTE_TOP_N_DEFAULT
        checkbox_style = {"display": "flex", "alignItems": "center"}
    else:
        options, default = TOP_N_OPTIONS, TOP_N_DEFAULT
        checkbox_style = {"display": "none"}

    value = current_top_n if current_top_n in options else default
    return (
        container_style,
        [{"label": f"Top {n}", "value": n} for n in options],
        value,
        checkbox_style,
    )


def _chart_height(breakdown, categories):
    """Marca/Submarca/Variante empilham ate 30 categorias (top N) numa
    unica coluna - a altura padrao (640px) nao da espaco suficiente pros
    rotulos de cada uma sem sobrepor perto da base da pilha. Cresce com o
    numero de categorias realmente exibidas, so pra essas 3 quebras."""
    if breakdown not in RANKED_BREAKDOWNS and breakdown != "embalagem_conteudo":
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


def _simple_average(values, categories, years=YEARS_DEFAULT):
    """Media aritmetica simples ano a ano de `values` entre `categories`,
    sem ponderar por volume/tamanho - usada quando o proprio indicador e
    um preco/taxa e o objetivo e olhar o nivel de preco em si, sem que
    categorias de maior volume vendido "puxem" a media (ver
    `INDICATORS["preco_medio_litros"]["average_mode"]`)."""
    result = {}
    for yr in years:
        vals = [values[cat][yr] for cat in categories if values.get(cat, {}).get(yr) is not None]
        result[yr] = sum(vals) / len(vals) if vals else None
    return result


def _build_blocks(breakdown, regiao_view, segmento_f, fabricante_f, marca_f, submarca_f, variante_f, subvariante_f, top_n, body_splash_f="Total", fabricante_outros=True):
    """Monta os dados de cada bloco (grafico + tabela + insight) pra
    combinacao atual de quebra/filtros/regiao - {indicador: dict(...)}.
    Usado tanto pelo callback que redesenha a tela (`update_charts`)
    quanto pelos botoes de exportar PowerPoint (`_export_pptx`), pra
    garantir que o arquivo exportado tenha exatamente os mesmos numeros
    exibidos na tela."""
    if not breakdown:
        breakdown = "segmento"
    if breakdown not in RANKED_BREAKDOWNS:
        top_n = _TOP_N

    blocks: dict[str, dict] = {}
    # categorias/valores ja resolvidos de cada bloco, indexado por
    # indicador - alimenta os blocos com `rank_with`/`weight_indicator`
    # (ver INDICATORS: "volume" precisa vir antes deles em INDICATOR_BLOCKS)
    resolved_categories: dict[str, list[str]] = {}
    resolved_values: dict[str, dict[str, dict[str, float]]] = {}

    for key in INDICATOR_BLOCKS:
        cfg = INDICATORS[key]
        rank_with = cfg.get("rank_with")
        categories, dim_col, filters, values_override, title, true_totals = build_selection(
            breakdown, regiao_view, segmento_f, fabricante_f, marca_f, submarca_f, variante_f, subvariante_f, key, top_n,
            categories_override=resolved_categories.get(rank_with) if rank_with else None,
            weight_indicator=cfg.get("weight_indicator"), body_splash_f=body_splash_f, fabricante_outros=fabricante_outros,
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
            if cfg.get("average_mode") == "simple":
                weighted_average = _simple_average(values, categories)
                average_label = "Média simples"
            elif weight_key:
                weighted_average = _weighted_average(values, resolved_values.get(weight_key, {}), categories)
                average_label = "Média ponderada"
            else:
                weighted_average = None
                average_label = "Média ponderada"
            fig = line_evolution_chart(
                df=df, indicator=key, dimension=dim_col, categories=categories, filters=filters,
                title=title, subtitle=subtitle, unit_label=cfg["unit_label"],
                value_decimals=value_decimals, is_percent=cfg["is_percent"],
                values_override=values, weighted_average=weighted_average, weighted_average_label=average_label,
            )
            fig.update_layout(autosize=True, width=None)
        else:
            values, true_totals, unit, decimals_override = _resolve_unit(key, values, categories, true_totals)
            value_decimals = decimals_override if decimals_override is not None else cfg["value_decimals"]
            insight_unit_label = unit or cfg["unit_label"]
            subtitle = f"{cfg['label']} ({unit})" if unit else cfg["label"]
            # com true_totals (Marca/Submarca/Variante = so um recorte
            # top N), o valor nominal que apareceria no topo da barra
            # seria so a soma do recorte exibido, nao o total real (e a
            # variacao ano a ano dessa soma nao e uma variacao de
            # mercado de verdade) - troca os dois por coverage_pct: a
            # soma da participacao (share) das categorias exibidas em
            # cada ano (ex.: Fabricante A 30% + Fabricante B 15% = 45%
            # no topo), com a "chave" entre colunas mostrando a variacao
            # dessa cobertura em pontos percentuais (ver
            # `alluvial_stack_chart`)
            coverage_pct = None
            if true_totals is not None and categories:
                coverage_pct = {
                    yr: (sum(values[cat][yr] for cat in categories) / true_totals[yr] * 100) if true_totals[yr] else 0.0
                    for yr in YEARS_DEFAULT
                }

            fig = alluvial_stack_chart(
                df=df, indicator=key, dimension=dim_col, categories=categories, filters=filters,
                title=title, subtitle=subtitle, values_override=values,
                value_scale=1.0, value_decimals=value_decimals, is_percent=cfg["is_percent"],
                show_total=bool(categories), coverage_pct=coverage_pct, true_totals=true_totals,
                height=_chart_height(breakdown, categories),
            )
            fig.update_layout(autosize=True, width=None)

        blocks[key] = dict(
            fig=fig, categories=categories, values=values, dim_col=dim_col, filters=filters,
            value_decimals=value_decimals, true_totals=true_totals, cfg=cfg,
            insight_unit_label=insight_unit_label,
        )

    return blocks


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
    Input("subvariante-filter", "value"),
    Input("top-n-selector", "value"),
    Input("body-splash-filter", "value"),
    Input("fabricante-outros-checkbox", "value"),
)
def update_charts(breakdown, regiao_view, segmento_f, fabricante_f, marca_f, submarca_f, variante_f, subvariante_f, top_n, body_splash_f, fabricante_outros_value):
    blocks = _build_blocks(
        breakdown, regiao_view, segmento_f, fabricante_f, marca_f, submarca_f, variante_f, subvariante_f, top_n, body_splash_f,
        fabricante_outros="incluir" in (fabricante_outros_value or []),
    )

    figs, tables, insights = [], [], []
    for key in INDICATOR_BLOCKS:
        b = blocks[key]
        table = _variation_table(b["categories"], b["values"], b["cfg"]["additive"], b["value_decimals"], b["true_totals"])
        insight = generate_insight(
            df, indicator=key, dimension=b["dim_col"], categories=b["categories"], filters=b["filters"],
            value_scale=1.0, value_decimals=b["value_decimals"], unit_label=b["insight_unit_label"],
            additive=b["cfg"]["additive"], values_override=b["values"], totals_override=b["true_totals"],
        )
        figs.append(b["fig"])
        tables.append(table)
        insights.append(insight)

    return (*figs, *tables, *insights)


def _make_export_callback(key):
    @app.callback(
        Output(f"download-{key}", "data"),
        Input(f"export-btn-{key}", "n_clicks"),
        State("dimension-dropdown", "value"),
        State("regiao-tabs", "value"),
        State("segmento-filter", "value"),
        State("fabricante-filter", "value"),
        State("marca-filter", "value"),
        State("submarca-filter", "value"),
        State("variante-filter", "value"),
        State("subvariante-filter", "value"),
        State("top-n-selector", "value"),
        State("body-splash-filter", "value"),
        State("fabricante-outros-checkbox", "value"),
        prevent_initial_call=True,
    )
    def export(n_clicks, breakdown, regiao_view, segmento_f, fabricante_f, marca_f, submarca_f, variante_f, subvariante_f, top_n, body_splash_f, fabricante_outros_value):
        blocks = _build_blocks(
            breakdown, regiao_view, segmento_f, fabricante_f, marca_f, submarca_f, variante_f, subvariante_f, top_n, body_splash_f,
            fabricante_outros="incluir" in (fabricante_outros_value or []),
        )
        b = blocks[key]
        insight = generate_insight(
            df, indicator=key, dimension=b["dim_col"], categories=b["categories"], filters=b["filters"],
            value_scale=1.0, value_decimals=b["value_decimals"], unit_label=b["insight_unit_label"],
            additive=b["cfg"]["additive"], values_override=b["values"], totals_override=b["true_totals"],
        )
        pptx_bytes = build_pptx(
            b["fig"], b["categories"], b["values"], b["cfg"]["additive"], b["value_decimals"], b["true_totals"],
            highlight_text=insight,
        )
        filename = f"{INDICATORS[key]['label'].replace(' ', '_')}.pptx"
        return dcc.send_bytes(pptx_bytes, filename)

    return export


for _key in INDICATOR_BLOCKS:
    _make_export_callback(_key)


def _build_price_unit_rows(breakdown, regiao_view, segmento_f, fabricante_f, marca_f, submarca_f, variante_f, subvariante_f, top_n, body_splash_f="Total", fabricante_outros=True):
    """Um waterfall por categoria (nao um unico grafico com todas juntas,
    como os outros 4 blocos): decompoe a variacao ano a ano do Valor com
    Presentes de cada categoria em efeito Unidades e efeito Preco Medio.
    Reaproveita o ranking do bloco Valor com Presentes (mesmas categorias
    que aparecem naquela aba) e busca Unidades para essas mesmas
    categorias (`categories_override`). Retorna uma lista de
    dict(cat, fig, insight) - usado tanto por `update_waterfall` (tela)
    quanto pelo botao de exportar (`export_price_unit`)."""
    if not breakdown:
        breakdown = "segmento"
    if breakdown not in RANKED_BREAKDOWNS:
        top_n = _TOP_N

    categories, dim_col, filters, valor_override, title, true_totals = build_selection(
        breakdown, regiao_view, segmento_f, fabricante_f, marca_f, submarca_f, variante_f, subvariante_f,
        "valor_com_presentes", top_n, body_splash_f=body_splash_f, fabricante_outros=fabricante_outros,
    )
    if not categories:
        return []

    if valor_override is not None:
        valor_values = valor_override
    else:
        valor_values = compute_values(
            df, "valor_com_presentes", dim_col, categories, YEARS_DEFAULT, filters,
            INDICATORS["valor_com_presentes"]["value_scale"],
        )

    _, _, _, unidades_override, _, _ = build_selection(
        breakdown, regiao_view, segmento_f, fabricante_f, marca_f, submarca_f, variante_f, subvariante_f,
        "unidades", top_n, categories_override=categories, body_splash_f=body_splash_f, fabricante_outros=fabricante_outros,
    )
    if unidades_override is not None:
        unidades_values = unidades_override
    else:
        unidades_values = compute_values(
            df, "unidades", dim_col, categories, YEARS_DEFAULT, filters, INDICATORS["unidades"]["value_scale"],
        )

    # mesma escala dinamica (milhoes/bilhoes) e mesmas casas decimais que
    # o bloco "Valor com Presentes" usa - reescala valor (e so valor: a
    # decomposicao Unidades/Preco continua exata pra qualquer fator de
    # escala uniforme aplicado a valor, ver docstring de
    # price_unit_waterfall_chart) em vez de um "R$ milhoes" fixo
    valor_values, _, unit_label, decimals_override = _resolve_unit("valor_com_presentes", valor_values, categories)
    value_decimals = decimals_override if decimals_override is not None else INDICATORS["valor_com_presentes"]["value_decimals"]
    subtitle = f"{INDICATORS['valor_com_presentes']['label']} em {unit_label}"

    result = []
    # waterfall totalizador (soma de todas as categorias exibidas) antes
    # dos especificos - so faz sentido quando as categorias exibidas
    # somam o total de verdade: Segmento (sempre exaustivo) e Fabricante
    # com o checkbox "Demais Fabricantes" marcado (`true_totals is None`,
    # ver `build_selection`); Marca/Submarca/Variante sao sempre so um
    # recorte top N - EMBALAGEM_BREAKDOWNS tambem nao combina com esta aba
    if breakdown == "segmento" or (breakdown == "fabricante" and true_totals is None):
        total_unidades = {yr: sum(unidades_values[cat][yr] for cat in categories) for yr in YEARS_DEFAULT}
        total_valor = {yr: sum(valor_values[cat][yr] for cat in categories) for yr in YEARS_DEFAULT}
        fig = price_unit_waterfall_chart(
            f"{title} > Total", total_unidades, total_valor,
            unit_label=subtitle, value_decimals=value_decimals,
        )
        insight = generate_price_unit_insight(total_unidades, total_valor)
        result.append(dict(cat="Total", fig=fig, insight=insight))

    for cat in categories:
        fig = price_unit_waterfall_chart(
            f"{title} > {cat}", unidades_values[cat], valor_values[cat],
            unit_label=subtitle, value_decimals=value_decimals,
        )
        insight = generate_price_unit_insight(unidades_values[cat], valor_values[cat])
        result.append(dict(cat=cat, fig=fig, insight=insight))
    return result


def _build_additions_bridge(indicator, breakdown, regiao_view, segmento_f, fabricante_f, marca_f, submarca_f, variante_f, subvariante_f, top_n, body_splash_f="Total", fabricante_outros=True):
    """(names, deltas, totals, title) pra uma aba "Adicoes de X" (ver
    ADDITIONS_TABS - `indicator` e "unidades" ou "valor_com_presentes")
    {ADDITIONS_YEAR0}->{ADDITIONS_YEAR1}": `totals` = {ano: total do
    indicador no filtro} pra essa UNICA transicao; `deltas[nome]` =
    contribuicao daquele nome pra diferenca entre os dois anos (a soma
    dos deltas de todos os `names` fecha EXATAMENTE com
    `totals[YEAR1] - totals[YEAR0]`).

    Quando a quebra e so um recorte top N (Marca/Submarca/Variante/Sub
    Variante - `true_totals` vem preenchido de `build_selection`),
    `names` inclui uma categoria residual "Outras"/"Demais outras" com
    o que nao esta no top N, garantindo essa soma exata; pra Segmento/
    Fabricante/Embalagem (todas as categorias exibidas ja fecham o
    total de verdade) nao ha residuo.

    Usado tanto pela tabela (`_additions_table`) quanto, apos reordenar
    por transicao (ver `_bridge_transition_order`), pelo grafico
    (`charts.unit_additions_bridge_chart`) - mesma fonte de dados pros
    dois, entao sempre batem."""
    if not breakdown:
        breakdown = "segmento"
    if breakdown not in RANKED_BREAKDOWNS:
        top_n = _TOP_N

    yr0, yr1 = ADDITIONS_YEAR0, ADDITIONS_YEAR1

    categories, dim_col, filters, values_override, title, true_totals = build_selection(
        breakdown, regiao_view, segmento_f, fabricante_f, marca_f, submarca_f, variante_f, subvariante_f,
        indicator, top_n, body_splash_f=body_splash_f, fabricante_outros=fabricante_outros,
    )
    if not categories:
        return [], {}, {}, title

    if values_override is not None:
        values = values_override
    else:
        values = compute_values(
            df, indicator, dim_col, categories, YEARS_DEFAULT, filters, INDICATORS[indicator]["value_scale"],
        )

    totals = {}
    for yr in (yr0, yr1):
        totals[yr] = true_totals[yr] if true_totals is not None else sum(values[cat][yr] for cat in categories)

    names = list(categories)
    deltas = {cat: values[cat][yr1] - values[cat][yr0] for cat in categories}

    if true_totals is not None:
        residual_label = "Demais outras" if "Outras" in categories else "Outras"
        residual0 = totals[yr0] - sum(values[cat][yr0] for cat in categories)
        residual1 = totals[yr1] - sum(values[cat][yr1] for cat in categories)
        names.append(residual_label)
        deltas[residual_label] = residual1 - residual0

    # ordem da TABELA: maior adicao primeiro - a ordem VISUAL do grafico
    # e recalculada a parte (ver _bridge_transition_order), nao usa esta
    names = sorted(names, key=lambda n: deltas[n], reverse=True)

    return names, deltas, totals, title


def _bridge_transition_order(names, deltas):
    """Ordem visual dos blocos de `charts.unit_additions_bridge_chart`:
    negativos em ordem DECRESCENTE (maior queda primeiro) seguidos dos
    positivos em ordem CRESCENTE (maior alta por ultimo, colado no
    pilar seguinte) - efeito "vale" entre os dois pilares cinzas."""
    negatives = sorted((n for n in names if deltas[n] < 0), key=lambda n: deltas[n])
    positives = sorted((n for n in names if deltas[n] >= 0), key=lambda n: deltas[n])
    return negatives + positives


@app.callback(
    Output("waterfall-container", "children"),
    Input("dimension-dropdown", "value"),
    Input("regiao-tabs", "value"),
    Input("segmento-filter", "value"),
    Input("fabricante-filter", "value"),
    Input("marca-filter", "value"),
    Input("submarca-filter", "value"),
    Input("variante-filter", "value"),
    Input("subvariante-filter", "value"),
    Input("top-n-selector", "value"),
    Input("body-splash-filter", "value"),
    Input("fabricante-outros-checkbox", "value"),
)
def update_waterfall(breakdown, regiao_view, segmento_f, fabricante_f, marca_f, submarca_f, variante_f, subvariante_f, top_n, body_splash_f, fabricante_outros_value):
    rows = _build_price_unit_rows(
        breakdown, regiao_view, segmento_f, fabricante_f, marca_f, submarca_f, variante_f, subvariante_f, top_n, body_splash_f,
        fabricante_outros="incluir" in (fabricante_outros_value or []),
    )
    if not rows:
        return html.P("Sem dados para esta combinação de filtros.", style={"color": "#888", "fontSize": "12px"})

    return [
        html.Div(
            style={"display": "flex", "gap": "20px", "flexWrap": "wrap", "alignItems": "center"},
            children=[
                dcc.Graph(figure=row["fig"], config={"responsive": False, "displayModeBar": False}),
                html.Div(
                    [html.B("Highlights"), html.P(row["insight"], style={"margin": "4px 0 0", "fontSize": "15.5px", "lineHeight": "1.5", "color": "#333"})],
                    style={"flex": "1", "minWidth": "260px", "maxWidth": "360px"},
                ),
            ],
        )
        for row in rows
    ]


@app.callback(
    Output("download-price-unit", "data"),
    Input("export-btn-price-unit", "n_clicks"),
    State("dimension-dropdown", "value"),
    State("regiao-tabs", "value"),
    State("segmento-filter", "value"),
    State("fabricante-filter", "value"),
    State("marca-filter", "value"),
    State("submarca-filter", "value"),
    State("variante-filter", "value"),
    State("subvariante-filter", "value"),
    State("top-n-selector", "value"),
    State("body-splash-filter", "value"),
    State("fabricante-outros-checkbox", "value"),
    prevent_initial_call=True,
)
def export_price_unit(n_clicks, breakdown, regiao_view, segmento_f, fabricante_f, marca_f, submarca_f, variante_f, subvariante_f, top_n, body_splash_f, fabricante_outros_value):
    rows = _build_price_unit_rows(
        breakdown, regiao_view, segmento_f, fabricante_f, marca_f, submarca_f, variante_f, subvariante_f, top_n, body_splash_f,
        fabricante_outros="incluir" in (fabricante_outros_value or []),
    )
    pptx_bytes = build_price_unit_pptx([(row["fig"], row["insight"]) for row in rows])
    return dcc.send_bytes(pptx_bytes, "Price_Unit.pptx")


def _additions_tab_result(cfg, breakdown, regiao_view, segmento_f, fabricante_f, marca_f, submarca_f, variante_f, subvariante_f, top_n, body_splash_f, fabricante_outros_value):
    """Logica compartilhada de todas as abas "Adicoes de X" (ver
    ADDITIONS_TABS) - so o `cfg` (indicador/rotulos daquela aba) muda
    entre elas, ver _register_additions_callback. Retorna tambem
    `names`/`deltas`/`indicator_cfg` (alem de fig/table/insight, usados
    pela tela) pra exportacao PowerPoint (ver export_additions) montar o
    PPTX com exatamente os mesmos numeros, sem recalcular."""
    names, deltas, totals, title = _build_additions_bridge(
        cfg["indicator"], breakdown, regiao_view, segmento_f, fabricante_f, marca_f, submarca_f, variante_f, subvariante_f, top_n, body_splash_f,
        fabricante_outros="incluir" in (fabricante_outros_value or []),
    )
    indicator_cfg = INDICATORS[cfg["indicator"]]
    order = _bridge_transition_order(names, deltas) if names else []
    fig = unit_additions_bridge_chart(
        title, ADDITIONS_YEAR0, ADDITIONS_YEAR1, totals, order, deltas,
        value_decimals=indicator_cfg["value_decimals"], unit_label=cfg["chart_unit_label"],
    )
    # SEM fig.update_layout(autosize=True, width=None) - ao contrario dos
    # outros graficos, este NAO e responsivo: a largura cresce com o
    # numero de blocos (ate 30 categorias), ver
    # charts.unit_additions_bridge_chart e o container com scroll
    # horizontal em app.layout (_additions_panel)
    table = _additions_table(names, deltas, indicator_cfg["value_decimals"])
    insight = generate_unit_additions_insight(
        names, deltas, totals, ADDITIONS_YEAR0, ADDITIONS_YEAR1,
        unit_label=indicator_cfg["unit_label"], indicator_label=cfg["insight_label"],
    )
    return fig, table, insight, names, deltas, indicator_cfg


def _register_additions_callback(cfg):
    """Registra os callbacks (tela + exportar PowerPoint) de uma aba
    "Adicoes de X" (ver ADDITIONS_TABS). Fabrica separada (em vez de um
    loop com `@app.callback` direto) pra `cfg` ficar preso por valor a
    cada callback via default de parametro, nao por referencia a
    variavel de loop (que apontaria pra ultima entrada de ADDITIONS_TABS
    em todas as chamadas)."""

    @app.callback(
        Output(cfg["graph_id"], "figure"),
        Output(cfg["table_id"], "children"),
        Output(cfg["insight_id"], "children"),
        Input("dimension-dropdown", "value"),
        Input("regiao-tabs", "value"),
        Input("segmento-filter", "value"),
        Input("fabricante-filter", "value"),
        Input("marca-filter", "value"),
        Input("submarca-filter", "value"),
        Input("variante-filter", "value"),
        Input("subvariante-filter", "value"),
        Input("top-n-selector", "value"),
        Input("body-splash-filter", "value"),
        Input("fabricante-outros-checkbox", "value"),
    )
    def update_additions(breakdown, regiao_view, segmento_f, fabricante_f, marca_f, submarca_f, variante_f, subvariante_f, top_n, body_splash_f, fabricante_outros_value, cfg=cfg):
        fig, table, insight, _names, _deltas, _indicator_cfg = _additions_tab_result(
            cfg, breakdown, regiao_view, segmento_f, fabricante_f, marca_f, submarca_f, variante_f, subvariante_f, top_n, body_splash_f, fabricante_outros_value,
        )
        return fig, table, insight

    @app.callback(
        Output(f"download-{cfg['key']}", "data"),
        Input(f"export-btn-{cfg['key']}", "n_clicks"),
        State("dimension-dropdown", "value"),
        State("regiao-tabs", "value"),
        State("segmento-filter", "value"),
        State("fabricante-filter", "value"),
        State("marca-filter", "value"),
        State("submarca-filter", "value"),
        State("variante-filter", "value"),
        State("subvariante-filter", "value"),
        State("top-n-selector", "value"),
        State("body-splash-filter", "value"),
        State("fabricante-outros-checkbox", "value"),
        prevent_initial_call=True,
    )
    def export_additions(n_clicks, breakdown, regiao_view, segmento_f, fabricante_f, marca_f, submarca_f, variante_f, subvariante_f, top_n, body_splash_f, fabricante_outros_value, cfg=cfg):
        fig, _table, insight, names, deltas, indicator_cfg = _additions_tab_result(
            cfg, breakdown, regiao_view, segmento_f, fabricante_f, marca_f, submarca_f, variante_f, subvariante_f, top_n, body_splash_f, fabricante_outros_value,
        )
        pptx_bytes = build_additions_pptx(
            fig, names, deltas, indicator_cfg["value_decimals"], ADDITIONS_YEAR0, ADDITIONS_YEAR1, highlight_text=insight,
        )
        filename = f"{cfg['tab_label'].replace(' ', '_').replace('→', '-')}.pptx"
        return dcc.send_bytes(pptx_bytes, filename)


for _additions_cfg in ADDITIONS_TABS:
    _register_additions_callback(_additions_cfg)


server = app.server  # WSGI entrypoint p/ producao (ex.: gunicorn app:server)

if __name__ == "__main__":
    app.run(debug=True)
