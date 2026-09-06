"""Graficos de evolucao anual, conforme ESCOPO.md secao 3:

- alluvial_stack_chart: para indicadores cumulativos/empilhaveis (Volume,
  Unidades, Share Unidades, Valor sem/com Presentes, Share Valor,
  Compradores) - barras empilhadas com fluxo curvo entre anos, no estilo
  da referencia em fonte/"exemplo sankey e alluvium.png".
- line_evolution_chart: para indicadores nao cumulativos (Penetracao,
  Vol. por Comprador, Frequencia, Preco Medio) - uma linha por categoria,
  sem empilhamento.

Uso tipico:

    from etl import build_dataset
    from charts import alluvial_stack_chart

    df = build_dataset()
    fig = alluvial_stack_chart(
        df,
        indicator="unidades",
        dimension="regiao",
        categories=["N+NE", "Sudeste", "C.Oeste", "Sul"],  # topo -> base
        filters={
            "segmento": "Total",
            "fabricante": "Total",
            "marca": "Total",
            "classificacao": "Total",
            "cod": "1",
        },
        title="Brasil > Todos os segmentos > Regioes",
        subtitle="Analise de Unidades",
        value_scale=1 / 1_000_000,
    )
    fig.write_html("volume_por_regiao.html")
"""

from __future__ import annotations

import plotly.graph_objects as go

from colors import get_color

YEARS_DEFAULT = ("Y2022", "Y2023", "Y2024", "Y2025")

# fonte padrao de todos os graficos (mesma usada no restante do app Dash)
FONT_FAMILY = "Roboto, -apple-system, Helvetica, Arial, sans-serif"

_BAR_OPACITY = 0.96
_FLOW_OPACITY = 0.6
_FLOW_WHITEN = 0.22  # 0-1: quanto a cor do fluxo e clareada em direcao ao branco
_BAR_HALF_WIDTH = 0.3
_CURVE_POINTS = 40

# variacao ano-a-ano: verde se positiva, vermelho se negativa
_POSITIVE = {"line": "#1E8E5A", "text": "#166B45", "bg": "rgba(210,245,227,0.95)"}
_NEGATIVE = {"line": "#C23B3B", "text": "#992E2E", "bg": "rgba(252,222,222,0.95)"}


def _change_style(pct: float) -> dict:
    return _POSITIVE if pct >= 0 else _NEGATIVE


def _smoothstep(t: float) -> float:
    return t * t * (3 - 2 * t)


def _hex_to_rgb(hexcolor: str) -> tuple[int, int, int]:
    hexcolor = hexcolor.lstrip("#")
    r, g, b = (int(hexcolor[i : i + 2], 16) for i in (0, 2, 4))
    return r, g, b


def _hex_to_rgba(hexcolor: str, alpha: float) -> str:
    r, g, b = _hex_to_rgb(hexcolor)
    return f"rgba({r},{g},{b},{alpha})"


def _muted_rgba(hexcolor: str, whiten: float = _FLOW_WHITEN, alpha: float = _FLOW_OPACITY) -> str:
    """Cor 'rebaixada' usada no fluxo alluvial entre as barras: mesma cor
    da barra, clareada em direcao ao branco e com menor opacidade."""
    r, g, b = _hex_to_rgb(hexcolor)
    r = round(r + (255 - r) * whiten)
    g = round(g + (255 - g) * whiten)
    b = round(b + (255 - b) * whiten)
    return f"rgba({r},{g},{b},{alpha})"


def _band_polygon(x0, x1, bottom0, top0, bottom1, top1, n=_CURVE_POINTS):
    """Pontos de um poligono fechado formando uma banda que flui de
    (x0, bottom0-top0) para (x1, bottom1-top1) com transicao suave
    (smoothstep), imitando o efeito de fluxo alluvial/sankey."""
    xs_top, ys_top = [], []
    xs_bottom, ys_bottom = [], []
    for i in range(n + 1):
        t = i / n
        s = _smoothstep(t)
        x = x0 + (x1 - x0) * t
        xs_top.append(x)
        ys_top.append(top0 + (top1 - top0) * s)
        xs_bottom.append(x)
        ys_bottom.append(bottom0 + (bottom1 - bottom0) * s)
    xs = xs_top + xs_bottom[::-1]
    ys = ys_top + ys_bottom[::-1]
    return xs, ys


def _format_value(value: float, decimals: int, is_percent: bool) -> str:
    text = f"{value:,.{decimals}f}"
    return f"{text}%" if is_percent else text


def compute_values(
    df,
    indicator: str,
    dimension: str,
    categories: list[str],
    years: tuple[str, ...] = YEARS_DEFAULT,
    filters: dict[str, str] | None = None,
    value_scale: float = 1.0,
) -> dict[str, dict[str, float]]:
    """Extrai {categoria: {ano: valor}} de `df` para um indicador/dimensao,
    aplicando os filtros fixos. Usada tanto pelos graficos quanto pelo
    gerador de insights (insights.py), para nao duplicar essa leitura."""
    filters = filters or {}
    subset = df
    for col, val in filters.items():
        subset = subset[subset[col] == val]
    return {
        cat: {
            yr: float(subset.loc[subset[dimension] == cat, f"{indicator}_{yr}"].sum())
            * value_scale
            for yr in years
        }
        for cat in categories
    }


def pct_change(prev: float | None, curr: float | None) -> float | None:
    if not prev:
        return None
    return (curr - prev) / prev * 100


def compute_variations(
    values: dict[str, dict[str, float]],
    categories: list[str],
    years: tuple[str, ...] = YEARS_DEFAULT,
    additive: bool = True,
    totals_override: dict[str, float] | None = None,
) -> dict[str, dict[str, list[float | None]]]:
    """Para cada categoria, a variacao percentual do valor e (se
    `additive`) a variacao de participacao (MS, em pontos percentuais)
    entre cada par de anos consecutivos, junto com o valor nominal do
    indicador e da participacao (MS) no ano final de cada transicao -
    usado pela tabela de variacoes do app (`{categoria: {"pct": [...],
    "share_pp": [...], "nominal": [...], "share_value": [...]}}`, uma
    entrada por transicao de ano). `totals_override` usa um total
    diferente da soma de `categories` pra calcular participacao (MS) -
    usado quando `categories` e so um top N (ex.: top 10 submarcas) e o
    MS de cada uma precisa ser sobre o mercado/marca inteiro, nao so
    sobre a soma das exibidas."""
    if totals_override is not None:
        totals = totals_override
    else:
        totals = {yr: sum(values[cat][yr] for cat in categories) for yr in years} if additive else {}
    result: dict[str, dict[str, list[float | None]]] = {}
    for cat in categories:
        pct: list[float | None] = []
        share_pp: list[float | None] = []
        nominal: list[float | None] = []
        share_value: list[float | None] = []
        for i in range(len(years) - 1):
            yr0, yr1 = years[i], years[i + 1]
            pct.append(pct_change(values[cat][yr0], values[cat][yr1]))
            nominal.append(values[cat][yr1])
            if additive and totals[yr0] and totals[yr1]:
                share0 = values[cat][yr0] / totals[yr0] * 100
                share1 = values[cat][yr1] / totals[yr1] * 100
                share_pp.append(share1 - share0)
                share_value.append(share1)
            else:
                share_pp.append(None)
                share_value.append(None)
        result[cat] = {"pct": pct, "share_pp": share_pp, "nominal": nominal, "share_value": share_value}
    return result


def _empty_figure(title: str, subtitle: str, years: tuple[str, ...], height: int, width: int) -> go.Figure:
    """Placeholder pra combinacoes de filtro sem nenhum dado (ex.: uma
    marca que nao vende num segmento especifico) - em vez de estourar
    tentando montar uma pilha vazia."""
    header = title if not subtitle else f"{title}<br><span style='font-size:13px;color:#666'>{subtitle}</span>"
    fig = go.Figure()
    fig.add_annotation(
        text="Sem dados para esta combinação de filtros",
        x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False,
        font=dict(color="#888", size=14),
    )
    fig.update_layout(
        title=dict(text=header, x=0.02, xanchor="left"),
        height=height,
        width=width,
        font=dict(family=FONT_FAMILY),
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(l=60, r=60, t=90, b=50),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
    )
    return fig


def alluvial_stack_chart(
    df,
    indicator: str,
    dimension: str,
    categories: list[str],
    years: tuple[str, ...] = YEARS_DEFAULT,
    filters: dict[str, str] | None = None,
    title: str = "",
    subtitle: str = "",
    value_scale: float = 1.0,
    value_decimals: int = 1,
    is_percent: bool = False,
    color_fn=get_color,
    height: int = 640,
    width: int = 760,
    values_override: dict[str, dict[str, float]] | None = None,
    show_total: bool = True,
) -> go.Figure:
    """Monta um grafico de barras empilhadas com fluxo curvo entre anos
    (estilo alluvial), com rotulos de valor/participacao e variacao %
    ano a ano, tanto por categoria quanto no total (`show_total=False`
    omite o rotulo do total e sua variacao - usado quando `categories` e
    um recorte tipo "top N" cuja soma nao e o total real).

    `categories` deve estar ordenada do topo para a base da pilha (como
    aparece visualmente), e todas as categorias devem somar o "total" que
    se quer mostrar (ex.: as regioes que compoem o T. Brasil).
    `filters` fixa as demais colunas categoricas (segmento, fabricante,
    marca, classificacao, cod) para isolar a fatia de dados desejada.
    `values_override` (opcional) substitui a leitura via `compute_values`
    por um dict {categoria: {ano: valor}} ja pronto - usado quando as
    categorias sao descobertas dinamicamente e incluem um grupo sintetico
    "Outros" que nao existe como valor literal na coluna `dimension`.
    """
    if not categories:
        return _empty_figure(title, subtitle, years, height, width)

    values = values_override or compute_values(df, indicator, dimension, categories, years, filters, value_scale)
    totals = {yr: sum(values[cat][yr] for cat in categories) for yr in years}

    # empilha de baixo para cima; `categories` foi informado do topo p/ base
    stack_order = list(reversed(categories))
    bottom = {cat: {} for cat in categories}
    top = {cat: {} for cat in categories}
    for yr in years:
        running = 0.0
        for cat in stack_order:
            bottom[cat][yr] = running
            running += values[cat][yr]
            top[cat][yr] = running

    x_positions = list(range(len(years)))
    fig = go.Figure()

    # pequena sobreposicao entre faixas adjacentes: sem isso, dois
    # poligonos preenchidos que apenas encostam (sem sobrepor) deixam uma
    # linha branca de anti-aliasing na costura, mesmo com bottom/top
    # matematicamente iguais
    seam_eps = max(totals.values()) * 0.004 if totals else 0.0

    # fluxo entre anos (cor rebaixada) primeiro, para as barras ficarem
    # por cima e com as bordas bem definidas
    for cat in categories:
        flow_fill = _muted_rgba(color_fn(cat))
        for i in range(len(years) - 1):
            yr0, yr1 = years[i], years[i + 1]
            xs, ys = _band_polygon(
                x_positions[i] + _BAR_HALF_WIDTH,
                x_positions[i + 1] - _BAR_HALF_WIDTH,
                bottom[cat][yr0] - seam_eps,
                top[cat][yr0] + seam_eps,
                bottom[cat][yr1] - seam_eps,
                top[cat][yr1] + seam_eps,
            )
            fig.add_trace(
                go.Scatter(
                    x=xs,
                    y=ys,
                    fill="toself",
                    mode="lines",
                    line=dict(width=0, color=flow_fill),
                    fillcolor=flow_fill,
                    hoverinfo="skip",
                    showlegend=False,
                )
            )

    # barras solidas em cada ano (cor cheia)
    for cat in categories:
        bar_fill = _hex_to_rgba(color_fn(cat), _BAR_OPACITY)
        for i, yr in enumerate(years):
            x0, x1 = i - _BAR_HALF_WIDTH, i + _BAR_HALF_WIDTH
            y_bottom, y_top = bottom[cat][yr] - seam_eps, top[cat][yr] + seam_eps
            fig.add_trace(
                go.Scatter(
                    x=[x0, x0, x1, x1],
                    y=[y_bottom, y_top, y_top, y_bottom],
                    fill="toself",
                    mode="lines",
                    line=dict(width=0, color=bar_fill),
                    fillcolor=bar_fill,
                    hoverinfo="skip",
                    showlegend=False,
                )
            )

    # rotulos de valor + participacao dentro de cada segmento, por ano
    # (faixas muito finas ganham fonte menor e perdem o sub-rotulo de
    # participacao, para nao virar sopa de letrinhas)
    max_total_for_labels = max(totals.values()) if totals else 0
    for cat in categories:
        for i, yr in enumerate(years):
            band_height = top[cat][yr] - bottom[cat][yr]
            ratio = band_height / max_total_for_labels if max_total_for_labels else 0
            if ratio < 0.02:
                continue  # faixa residual: sem espaco para rotulo legivel
            mid = (bottom[cat][yr] + top[cat][yr]) / 2
            value_text = _format_value(values[cat][yr], value_decimals, is_percent)
            show_share = not is_percent and totals[yr] != 0 and ratio >= 0.08
            share_text = f"{values[cat][yr] / totals[yr] * 100:.1f}%" if show_share else ""
            label = value_text if not share_text else f"{value_text}<br>{share_text}"
            fig.add_annotation(
                x=i,
                y=mid,
                text=label,
                showarrow=False,
                xanchor="center",
                font=dict(color="white", size=13 if ratio >= 0.08 else 10),
                align="center",
            )

    # rotulo do total no topo de cada coluna + variacao % do total ano a
    # ano (chave/bracket) - so fazem sentido quando as categorias somam o
    # total real; num recorte tipo "top N" (algumas submarcas/variantes
    # descartadas do ranking) esse "total" seria so a soma do que sobrou
    # no grafico, nao o total de verdade, entao o chamador pode pedir
    # pra omitir com show_total=False
    max_total = max(totals.values()) if totals else 0
    if show_total:
        for i, yr in enumerate(years):
            fig.add_annotation(
                x=i,
                y=top[categories[0]][yr] + max_total * 0.04,
                text=f"<b>{totals[yr]:,.{value_decimals}f}</b>",
                showarrow=False,
                xanchor="center",
                font=dict(color="#222222", size=17),
            )

        # variacao % do total, ano a ano: "chave" retangular (bracket) numa
        # fileira fixa acima das colunas - sobe reto a partir do topo da
        # coluna i, corre na horizontal (por baixo do pill) e desce com
        # seta no topo da coluna i+1 - igual a referencia em fonte/
        # "exemplo sankey e alluvium.png" (nao e uma curva; sao segmentos
        # retos com cantos retos)
        pill_y = max_total * 1.20
        riser_gap = max_total * 0.13
        # a subida e o pouso ficam na mesma altura (y0/y1 iguais a antes),
        # mas deslocados horizontalmente para os dois lados do centro da
        # coluna - a seta que chega termina um pouco antes do centro, a
        # que parte do proximo bracket comeca um pouco depois - assim nao
        # ficam coladas
        junction_dx = 0.07
        connector_gray = "rgba(128,128,128,0.7)"
        for i in range(len(years) - 1):
            yr0, yr1 = years[i], years[i + 1]
            if totals[yr0]:
                pct = (totals[yr1] - totals[yr0]) / totals[yr0] * 100
                style = _change_style(pct)
                x_mid = (i + i + 1) / 2
                x_start = i + junction_dx
                x_end = (i + 1) - junction_dx
                y0 = top[categories[0]][yr0] + riser_gap
                y1 = top[categories[0]][yr1] + riser_gap
                fig.add_trace(
                    go.Scatter(
                        x=[x_start, x_start, x_end, x_end],
                        y=[y0, pill_y, pill_y, y1],
                        mode="lines",
                        line=dict(color=connector_gray, width=0.9),
                        hoverinfo="skip",
                        showlegend=False,
                    )
                )
                fig.add_trace(
                    go.Scatter(
                        x=[x_end],
                        y=[y1],
                        mode="markers",
                        marker=dict(symbol="triangle-down", size=6, color=connector_gray),
                        hoverinfo="skip",
                        showlegend=False,
                    )
                )
                fig.add_annotation(
                    x=x_mid,
                    y=pill_y,
                    text=f"<b>{pct:+.1f}%</b>",
                    showarrow=False,
                    bordercolor=style["line"],
                    borderwidth=1,
                    borderpad=7,
                    bgcolor=style["bg"],
                    font=dict(color=style["text"], size=11),
                )
    else:
        pill_y = max_total * 1.08

    # rotulos de categoria na direita, alinhados ao ultimo ano.
    # ancorado por dados (xref="x"), rente a borda da ultima barra, ligado
    # a ela por uma linha fina - a margem direita (110px) garante que o
    # texto nao seja cortado mesmo quando o grafico e redimensionado.
    last = years[-1]
    bar_edge_x = x_positions[-1] + _BAR_HALF_WIDTH
    line_x0 = bar_edge_x + 0.03
    line_x1 = bar_edge_x + 0.16
    label_x = bar_edge_x + 0.2
    for cat in categories:
        mid = (bottom[cat][last] + top[cat][last]) / 2
        fig.add_trace(
            go.Scatter(
                x=[line_x0, line_x1],
                y=[mid, mid],
                mode="lines",
                line=dict(color=_hex_to_rgba(color_fn(cat), 0.55), width=0.8),
                hoverinfo="skip",
                showlegend=False,
            )
        )
        fig.add_annotation(
            x=label_x,
            y=mid,
            text=cat,
            showarrow=False,
            xanchor="left",
            font=dict(color=color_fn(cat), size=11),
        )

    header = title if not subtitle else f"{title}<br><span style='font-size:13px;color:#666'>{subtitle}</span>"
    fig.update_layout(
        title=dict(text=header, x=0.02, xanchor="left"),
        height=height,
        width=width,
        font=dict(family=FONT_FAMILY),
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(l=10, r=110, t=90, b=50),
        xaxis=dict(
            tickmode="array",
            tickvals=x_positions,
            ticktext=[y.replace("Y", "") for y in years],
            showgrid=False,
            zeroline=False,
            range=[-0.6, len(years) - 1 + _BAR_HALF_WIDTH + 0.35],
        ),
        yaxis=dict(visible=False, range=[0, pill_y * 1.15]),
    )
    return fig


def line_evolution_chart(
    df,
    indicator: str,
    dimension: str,
    categories: list[str],
    years: tuple[str, ...] = YEARS_DEFAULT,
    filters: dict[str, str] | None = None,
    title: str = "",
    subtitle: str = "",
    metric_label: str = "",
    unit_label: str = "",
    value_decimals: int = 1,
    is_percent: bool = False,
    color_fn=get_color,
    height: int = 480,
    width: int = 760,
    values_override: dict[str, dict[str, float]] | None = None,
    weighted_average: dict[str, float | None] | None = None,
    weighted_average_label: str = "Média ponderada",
) -> go.Figure:
    """Grafico de linha para indicadores nao cumulativos/nao empilhaveis
    (Penetracao, Vol. por Comprador, Frequencia, Preco Medio): uma linha
    por categoria, sem empilhamento, pois sao medias/taxas e nao somas.
    `values_override`: ver docstring de `alluvial_stack_chart`.
    `weighted_average`: {ano: valor} de uma media ponderada entre as
    categorias (tipicamente por Volume - ver `app._weighted_average`),
    desenhada como uma linha tracejada extra pra dar o "resumo" do
    indicador no periodo (uma media simples entre categorias ignoraria
    o tamanho de cada uma).
    """
    values = values_override or compute_values(df, indicator, dimension, categories, years, filters)

    x_positions = list(range(len(years)))
    fig = go.Figure()

    # linha suavizada (spline) com marcador pequeno de preenchimento
    # branco e borda na cor da categoria - sem rotulo de valor por ponto
    # (a tabela ao lado ja traz esses numeros; com muitas categorias os
    # rotulos se sobrepunham nas linhas). O nome da categoria fica direto
    # ao lado do fim da linha (em vez de legenda padrao do Plotly), pra
    # nao disputar espaco com o titulo.
    for cat in categories:
        color = color_fn(cat)
        y_values = [values[cat][yr] for yr in years]
        fig.add_trace(
            go.Scatter(
                x=x_positions,
                y=y_values,
                mode="lines+markers",
                name=cat,
                line=dict(color=color, width=2.5, shape="spline", smoothing=0.7),
                marker=dict(size=6, color="white", line=dict(color=color, width=1.5)),
                showlegend=False,
            )
        )
        fig.add_annotation(
            x=x_positions[-1],
            xshift=8,
            y=y_values[-1],
            text=cat,
            showarrow=False,
            xanchor="left",
            font=dict(color=color, size=11),
        )

    if weighted_average is not None:
        avg_color = "#666666"
        y_values = [weighted_average.get(yr) for yr in years]
        fig.add_trace(
            go.Scatter(
                x=x_positions,
                y=y_values,
                mode="lines+markers",
                name=weighted_average_label,
                line=dict(color=avg_color, width=2, dash="dash", shape="spline", smoothing=0.7),
                marker=dict(size=5, color="white", line=dict(color=avg_color, width=1.5)),
                connectgaps=True,
                showlegend=False,
            )
        )
        if y_values[-1] is not None:
            # unica linha com rotulo de valor + variacao sobre o ano
            # anterior: "Media ponderada (122.2, +5.3%)" em vez de um
            # numero por ponto (ver comentario acima)
            value_text = _format_value(y_values[-1], value_decimals, is_percent)
            change_pct = pct_change(y_values[-2], y_values[-1]) if len(y_values) >= 2 else None
            avg_label = (
                f"{weighted_average_label} ({value_text}, {change_pct:+.1f}%)"
                if change_pct is not None
                else f"{weighted_average_label} ({value_text})"
            )
            fig.add_annotation(
                x=x_positions[-1],
                xshift=8,
                y=y_values[-1],
                text=avg_label,
                showarrow=False,
                xanchor="left",
                font=dict(color=avg_color, size=12),
            )

    subtitle_full = f"{subtitle} ({metric_label})" if subtitle and metric_label else subtitle or metric_label
    header = title if not subtitle_full else f"{title}<br><span style='font-size:13px;color:#666'>{subtitle_full}</span>"
    fig.update_layout(
        title=dict(text=header, x=0.02, xanchor="left"),
        height=height,
        width=width,
        font=dict(family=FONT_FAMILY),
        plot_bgcolor="white",
        paper_bgcolor="white",
        # margem direita maior que os outros graficos: o rotulo da media
        # ponderada inclui o valor ("Media ponderada (2,095.1)"), bem mais
        # largo que um nome de categoria sozinho
        margin=dict(l=60, r=185, t=90, b=50),
        xaxis=dict(
            tickmode="array",
            tickvals=x_positions,
            ticktext=[y.replace("Y", "") for y in years],
            showgrid=False,
            zeroline=False,
            range=[-0.3, len(years) - 1 + 0.5],
        ),
        yaxis=dict(
            title=unit_label or None,
            showgrid=True,
            gridcolor="#eeeeee",
            zeroline=False,
            rangemode="tozero",
        ),
        showlegend=False,
    )
    return fig


def price_unit_effects(
    unidades: dict[str, float], valor: dict[str, float], years: tuple[str, ...] = YEARS_DEFAULT,
) -> list[dict]:
    """Decompoe a variacao ano a ano do "Valor com Presentes" em efeito
    Unidades (volume vendido) e efeito Preco Medio, dado que Valor =
    Unidades x Preco - uma entrada por transicao de ano (`{yr0, yr1,
    base, unit_effect, price_effect, unit_pct, price_pct, total_pct}`).
    Usado tanto por `price_unit_waterfall_chart` (barras) quanto por
    `insights.generate_price_unit_insight` (texto) - mesma formula nos
    dois lugares. O preco usado aqui e DERIVADO (valor/unidades) - nao a
    coluna "Preco Medio" da planilha, que nao reconcilia exatamente com
    valor/unidades - e por isso os dois efeitos somam exatamente a
    variacao real do Valor, sem residuo:

        efeito Unidades (ano N -> N+1) = (unidades[N+1] - unidades[N]) * preco[N]
        efeito Preco    (ano N -> N+1) = unidades[N+1] * (preco[N+1] - preco[N])
    """
    price = {yr: (valor[yr] / unidades[yr] if unidades.get(yr) else 0.0) for yr in years}
    effects = []
    for i in range(len(years) - 1):
        yr0, yr1 = years[i], years[i + 1]
        base = valor[yr0]
        unit_effect = (unidades[yr1] - unidades[yr0]) * price[yr0]
        price_effect = unidades[yr1] * (price[yr1] - price[yr0])
        effects.append(
            dict(
                yr0=yr0, yr1=yr1, base=base,
                unit_effect=unit_effect, price_effect=price_effect,
                unit_pct=(unit_effect / base * 100) if base else None,
                price_pct=(price_effect / base * 100) if base else None,
                total_pct=((valor[yr1] - valor[yr0]) / base * 100) if base else None,
            )
        )
    return effects


def price_unit_waterfall_chart(
    title: str,
    unidades: dict[str, float],
    valor: dict[str, float],
    years: tuple[str, ...] = YEARS_DEFAULT,
    unit_label: str = "R$ milhões",
    value_decimals: int = 2,
    height: int = 460,
    width: int = 760,
) -> go.Figure:
    """Waterfall da decomposicao de `price_unit_effects` (ver docstring
    la pra formula/racional) pra uma unica categoria: uma barra por ano
    (cinza, valor absoluto) com duas barras de efeito (verde/vermelho)
    entre cada par de anos - chave com a variacao % do total em cima
    (igual a `alluvial_stack_chart`) e CAGR do periodo no canto superior
    direito. `title` e o breadcrumb completo (ex.: "T. Brasil >
    Segmentos > Feminino"), no mesmo formato/alinhamento dos outros
    graficos - ver `build_selection`.
    """
    effects = price_unit_effects(unidades, valor, years)

    def _year_label(yr: str) -> str:
        return yr.replace("Y", "")

    x_ticktext = [_year_label(years[0])]
    measures = ["absolute"]
    y_values = [valor[years[0]]]
    bar_text = [f"<b>{valor[years[0]]:,.{value_decimals}f}</b>"]

    # (pct do total, indice da barra-ano inicial, indice da barra-ano
    # final, valor inicial, valor final) - pra desenhar a chave em cima
    brackets: list[tuple[float | None, int, int, float, float]] = []
    for i, eff in enumerate(effects):
        yr1 = eff["yr1"]
        for label, effect, pct in (
            ("Unidades", eff["unit_effect"], eff["unit_pct"]),
            ("Preço", eff["price_effect"], eff["price_pct"]),
        ):
            x_ticktext.append(label)
            measures.append("relative")
            y_values.append(effect)
            pct_text = f"{pct:.1f}%" if pct is not None else ""
            effect_color = _POSITIVE["text"] if effect >= 0 else _NEGATIVE["text"]
            bar_text.append(
                f"<span style='font-size:10px;color:{effect_color}'>{pct_text}</span>"
                f"<br><b>{effect:,.{value_decimals}f}</b>"
            )

        x_ticktext.append(_year_label(yr1))
        measures.append("total")
        y_values.append(valor[yr1])
        bar_text.append(f"<b>{valor[yr1]:,.{value_decimals}f}</b>")

        brackets.append((eff["total_pct"], i * 3, i * 3 + 3, eff["base"], valor[yr1]))

    # eixo x NUMERICO (0..N), com os rotulos de texto so no tickmode -
    # nao um eixo categorico "de verdade": as linhas/marcadores da chave
    # (abaixo) usam posicoes fracionarias (ex.: 0.18) que precisam
    # interpolar nesse mesmo eixo. Misturar um eixo categorico (que so
    # aceita as strings originais como posicoes) com tracos numericos cria
    # categorias fantasma pra cada posicao fracionaria, distorcendo tudo.
    x_positions = list(range(len(x_ticktext)))

    fig = go.Figure()
    fig.add_trace(
        go.Waterfall(
            x=x_positions,
            y=y_values,
            measure=measures,
            text=bar_text,
            textposition="outside",
            textfont=dict(size=13, family=FONT_FAMILY),
            increasing=dict(marker=dict(color=_POSITIVE["line"])),
            decreasing=dict(marker=dict(color=_NEGATIVE["line"])),
            totals=dict(marker=dict(color="#AFAFAF")),
            connector=dict(line=dict(color="rgba(150,150,150,0.5)", width=1)),
            width=0.62,
            showlegend=False,
        )
    )

    max_total = max(valor.values()) if valor else 0
    pill_y = max_total * 1.24
    riser_gap = max_total * 0.1
    junction_dx = 0.18
    connector_gray = "rgba(128,128,128,0.7)"
    for pct, i0, i1, y0_val, y1_val in brackets:
        if pct is None:
            continue
        style = _change_style(pct)
        x_mid = (i0 + i1) / 2
        x_start = i0 + junction_dx
        x_end = i1 - junction_dx
        y0 = y0_val + riser_gap
        y1 = y1_val + riser_gap
        fig.add_trace(
            go.Scatter(
                x=[x_start, x_start, x_end, x_end],
                y=[y0, pill_y, pill_y, y1],
                mode="lines",
                line=dict(color=connector_gray, width=0.9),
                hoverinfo="skip",
                showlegend=False,
            )
        )
        fig.add_trace(
            go.Scatter(
                x=[x_end],
                y=[y1],
                mode="markers",
                marker=dict(symbol="triangle-down", size=6, color=connector_gray),
                hoverinfo="skip",
                showlegend=False,
            )
        )
        fig.add_annotation(
            x=x_mid,
            y=pill_y,
            text=f"<b>{pct:+.1f}%</b>",
            showarrow=False,
            bordercolor=style["line"],
            borderwidth=1,
            borderpad=7,
            bgcolor=style["bg"],
            font=dict(color=style["text"], size=11),
        )

    # CAGR do periodo inteiro (primeiro -> ultimo ano), canto superior
    # direito - igual a referencia do usuario
    first_val, last_val = valor[years[0]], valor[years[-1]]
    n_periods = len(years) - 1
    cagr = (last_val / first_val) ** (1 / n_periods) - 1 if first_val and n_periods else None
    if cagr is not None:
        fig.add_annotation(
            x=1.0, xref="paper", y=1.14, yref="paper",
            text=f"CAGR = {cagr * 100:+.1f}%",
            showarrow=False,
            xanchor="right",
            bordercolor="#888", borderwidth=1, borderpad=5,
            bgcolor="white",
            font=dict(color="#333", size=11),
        )

    header = title if not unit_label else f"{title}<br><span style='font-size:13px;color:#666'>{unit_label}</span>"
    fig.update_layout(
        title=dict(text=header, x=0.02, xanchor="left"),
        height=height,
        width=width,
        font=dict(family=FONT_FAMILY),
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(l=50, r=30, t=90, b=40),
        xaxis=dict(
            tickmode="array",
            tickvals=x_positions,
            ticktext=x_ticktext,
            showgrid=False,
            zeroline=False,
            range=[-0.6, x_positions[-1] + 0.6],
        ),
        yaxis=dict(visible=False, range=[0, pill_y * 1.15]),
        showlegend=False,
    )
    return fig
