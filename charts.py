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
) -> go.Figure:
    """Monta um grafico de barras empilhadas com fluxo curvo entre anos
    (estilo alluvial), com rotulos de valor/participacao e variacao %
    ano a ano, tanto por categoria quanto no total.

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
            share_text = f"{values[cat][yr] / totals[yr] * 100:.0f}%" if show_share else ""
            label = value_text if not share_text else f"{value_text}<br>{share_text}"
            fig.add_annotation(
                x=i,
                y=mid,
                text=label,
                showarrow=False,
                xanchor="center",
                font=dict(color="white", size=12 if ratio >= 0.08 else 9),
                align="center",
            )

    # rotulo do total no topo de cada coluna
    max_total = max(totals.values()) if totals else 0
    for i, yr in enumerate(years):
        fig.add_annotation(
            x=i,
            y=top[categories[0]][yr] + max_total * 0.04,
            text=f"<b>{totals[yr]:,.1f}</b>",
            showarrow=False,
            xanchor="center",
            font=dict(color="#222222", size=16),
        )

    # variacao % do total, ano a ano: "chave" retangular (bracket) numa
    # fileira fixa acima das colunas - sobe reto a partir do topo da coluna
    # i, corre na horizontal (por baixo do pill) e desce com seta no topo
    # da coluna i+1 - igual a referencia em fonte/"exemplo sankey e
    # alluvium.png" (nao e uma curva; sao segmentos retos com cantos retos)
    pill_y = max_total * 1.20
    riser_gap = max_total * 0.13
    # a subida e o pouso ficam na mesma altura (y0/y1 iguais a antes), mas
    # deslocados horizontalmente para os dois lados do centro da coluna -
    # a seta que chega termina um pouco antes do centro, a que parte do
    # proximo bracket comeca um pouco depois - assim nao ficam coladas
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

    # variacao % por categoria, ano a ano, no meio de cada fluxo
    # (mesma logica de faixa minima usada nos rotulos de valor)
    for cat in categories:
        for i in range(len(years) - 1):
            yr0, yr1 = years[i], years[i + 1]
            avg_height = (
                (top[cat][yr0] - bottom[cat][yr0]) + (top[cat][yr1] - bottom[cat][yr1])
            ) / 2
            ratio = avg_height / max_total_for_labels if max_total_for_labels else 0
            if ratio < 0.03:
                continue
            if values[cat][yr0]:
                pct = (values[cat][yr1] - values[cat][yr0]) / values[cat][yr0] * 100
                x_mid = (i + i + 1) / 2
                y_mid = (
                    (bottom[cat][yr0] + top[cat][yr0]) / 2
                    + (bottom[cat][yr1] + top[cat][yr1]) / 2
                ) / 2
                fig.add_annotation(
                    x=x_mid,
                    y=y_mid,
                    text=f"{pct:+.0f}%",
                    showarrow=False,
                    bordercolor="#ffffff",
                    borderwidth=1,
                    borderpad=2,
                    bgcolor="rgba(255,255,255,0.85)",
                    font=dict(color="#333333", size=10),
                )

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
        margin=dict(l=60, r=110, t=90, b=50),
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
) -> go.Figure:
    """Grafico de linha para indicadores nao cumulativos/nao empilhaveis
    (Penetracao, Vol. por Comprador, Frequencia, Preco Medio): uma linha
    por categoria, sem empilhamento, pois sao medias/taxas e nao somas.
    `values_override`: ver docstring de `alluvial_stack_chart`.
    """
    values = values_override or compute_values(df, indicator, dimension, categories, years, filters)

    x_positions = list(range(len(years)))
    fig = go.Figure()

    # rotulo de categoria fica direto ao lado do fim da linha (em vez de
    # legenda padrao do Plotly), pra nao disputar espaco com o titulo
    for cat in categories:
        color = color_fn(cat)
        y_values = [values[cat][yr] for yr in years]
        text = [_format_value(v, value_decimals, is_percent) for v in y_values]
        fig.add_trace(
            go.Scatter(
                x=x_positions,
                y=y_values,
                mode="lines+markers+text",
                name=cat,
                text=text,
                textposition="top center",
                textfont=dict(color=color, size=11),
                line=dict(color=color, width=2.5),
                marker=dict(color=color, size=7),
                showlegend=False,
            )
        )
        fig.add_annotation(
            x=1.0,
            xref="paper",
            xshift=8,
            y=y_values[-1],
            text=cat,
            showarrow=False,
            xanchor="left",
            font=dict(color=color, size=11),
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
        margin=dict(l=60, r=90, t=90, b=50),
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
