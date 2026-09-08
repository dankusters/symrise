"""Exportacao de um bloco (grafico + tabela de variacao) para PowerPoint:
slide 1 reproduz o layout da tela (grafico a esquerda, tabela de
variacao a direita); se a tabela nao couber inteira no slide 1 (Marca/
Submarca/Variante podem chegar a 30 categorias no top N), o restante
continua em slides seguintes, so com a tabela (largura cheia).

Reaproveita `compute_variations` (mesma funcao usada pela tabela HTML do
app) pra garantir que os numeros exportados sejam identicos aos exibidos
na tela - so muda a camada de apresentacao (python-pptx em vez de Dash).
A tabela vira uma tabela PPTX nativa (editavel no PowerPoint), estilizada
o mais proximo possivel da tela: mesmas cores de alta/baixa, valor
nominal em cinza entre parenteses, categoria em negrito.
"""

from __future__ import annotations

import os
from io import BytesIO

import plotly.graph_objects as go
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

from charts import YEARS_DEFAULT, compute_variations
from etl import SOURCE_PATH

_SLIDE_WIDTH = Inches(13.333)
_SLIDE_HEIGHT = Inches(7.5)
_MARGIN = Inches(0.35)
_GAP = Inches(0.3)

# fonte de todo texto exportado (tabela, legenda, Highlights) - mesma
# familia usada na tela (assets/fonts.css), so a variante condensada
# (mais estreita, cabe melhor nas celulas apertadas da tabela)
_FONT_NAME = "Roboto Condensed"

# logo Symrise + titulo, canto superior esquerdo de todo slide - mesmo
# arquivo (recortado, sem a folga em branco a direita do SVG original
# em assets/SY1.DE_BIG.svg) e mesmo texto ao lado usados no cabecalho
# da tela (ver app.py)
_LOGO_PATH = os.path.join(os.path.dirname(__file__), "assets", "symrise_logo.png")
_LOGO_HEIGHT = Inches(0.28)
_LOGO_ASPECT = 1567 / 371  # dimensoes reais (px) de symrise_logo.png
_LOGO_WIDTH = Emu(int(_LOGO_HEIGHT * _LOGO_ASPECT))
_LOGO_GAP = Inches(0.1)
_TITLE_TEXT = "Worldpanel Dashboard"
_TITLE_GAP = Inches(0.12)  # espaco entre o logo e o titulo, na horizontal
# topo do conteudo (grafico/tabela) de todo slide - desce um pouco pra
# abrir espaco pro logo, sem sobrepor
_CONTENT_TOP = Emu(int(_MARGIN + _LOGO_HEIGHT + _LOGO_GAP))

# rodape com a fonte dos dados, canto inferior direito de todo slide -
# base do conteudo sobe um pouco pra abrir espaco, sem sobrepor (mesma
# logica do logo, no topo)
_FOOTER_TEXT = f"Fonte: {os.path.basename(SOURCE_PATH)}"
_FOOTER_HEIGHT = Inches(0.2)
_FOOTER_GAP = Inches(0.05)
_FOOTER_WIDTH = Inches(4.5)
_CONTENT_BOTTOM = Emu(int(_SLIDE_HEIGHT - _MARGIN - _FOOTER_HEIGHT - _FOOTER_GAP))


def _add_logo(slide):
    slide.shapes.add_picture(_LOGO_PATH, _MARGIN, _MARGIN, height=_LOGO_HEIGHT)

    title_left = Emu(int(_MARGIN + _LOGO_WIDTH + _TITLE_GAP))
    title_width = Inches(4.0)
    txbox = slide.shapes.add_textbox(title_left, _MARGIN, title_width, _LOGO_HEIGHT)
    tf = txbox.text_frame
    tf.word_wrap = False
    tf.margin_top = 0
    tf.margin_bottom = 0
    tf.margin_left = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    run = tf.paragraphs[0].add_run()
    run.text = _TITLE_TEXT
    run.font.name = _FONT_NAME
    run.font.bold = True
    run.font.size = Pt(14)
    run.font.color.rgb = RGBColor(0x22, 0x22, 0x22)


def _add_footer(slide):
    left = Emu(int(_SLIDE_WIDTH - _MARGIN - _FOOTER_WIDTH))
    top = Emu(int(_SLIDE_HEIGHT - _MARGIN - _FOOTER_HEIGHT))
    txbox = slide.shapes.add_textbox(left, top, _FOOTER_WIDTH, _FOOTER_HEIGHT)
    tf = txbox.text_frame
    tf.word_wrap = False
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.RIGHT
    run = p.add_run()
    run.text = _FOOTER_TEXT
    run.font.name = _FONT_NAME
    run.font.size = Pt(7)
    run.font.color.rgb = RGBColor(0xAA, 0xAA, 0xAA)

# fracao da largura util (descontada a margem) reservada pro grafico -
# espelha a proporcao "flex: 5" grafico / "flex: 4" tabela do layout na
# tela (5/9 =~ 0.556)
_CHART_WIDTH_FRACTION = 5 / 9

# "scale to fit": tamanho de fonte/margem da tabela em tamanho CHEIO
# (poucas linhas, cabe sem encolher) - diferente pro slide combinado
# (tabela divide espaco com o grafico, coluna mais estreita) e pro
# slide de continuacao (so tabela, largura inteira) - mesmos valores
# que o codigo ja usava antes de existir o scale-to-fit, agora so o
# TETO em vez de fixo.
_COMBO_HEADER_FONT_MAX = 10.0
_COMBO_BODY_FONT_MAX = 9.0
_FULL_HEADER_FONT_MAX = 12.0
_FULL_BODY_FONT_MAX = 11.0
_ROW_MARGIN_MAX = 2.0  # pt, margem topo/base de cada celula em tamanho cheio

# altura de linha aproximada, como multiplo do tamanho da fonte (o
# formato de tabela do pptx nao expoe medida de texto de verdade -
# 1.28 e uma estimativa razoavel pra fontes sans-serif comuns)
_TABLE_LINE_HEIGHT_MULT = 1.28

# nao encolhe fonte/margem alem deste fator do tamanho cheio (~55%,
# ficaria ilegivel abaixo disso) - o que nao couber nem no piso
# transborda pro slide de continuacao seguinte
_TABLE_SCALE_FLOOR = 0.55


def _fit_table(n_rows, area_height, show_share, header_font_max, body_font_max):
    """"Scale to fit": fonte/margem da tabela pra caber as `n_rows`
    linhas de dados (+ cabecalho) em `area_height` (EMU) num UNICO
    slide - comeca no tamanho cheio (`header_font_max`/`body_font_max`)
    e encolhe fonte+margem junto (mesma escala pros dois), proporcional
    ao excesso de linhas, ate `_TABLE_SCALE_FLOOR`. Estima a altura
    necessaria linearmente a partir do tamanho da fonte (ver
    `_TABLE_LINE_HEIGHT_MULT`), sem medir texto de verdade - aproximado,
    mas evita tanto o corte cego em N linhas fixas (que nao sabia se
    cabia mais ou menos que isso) quanto o excesso reduzir a fonte
    quando na verdade cabia inteiro em tamanho cheio.

    Se nem no piso tudo couber, retorna quantas linhas cabem nesse piso -
    o resto e responsabilidade do chamador (mais um slide, ver
    `build_pptx`). Retorna (header_font_pt, body_font_pt, margin_pt,
    rows_that_fit)."""
    area_pt = area_height / 12700  # EMU -> pt (1pt = 12700 EMU)
    lines_per_row = 2 if show_share else 1
    # altura necessaria(s) = k_total * s (linear na escala s, antes de
    # bater nos pisos - por isso da pra resolver s direto por divisao)
    k_header = header_font_max * _TABLE_LINE_HEIGHT_MULT + 2 * _ROW_MARGIN_MAX
    k_row = lines_per_row * body_font_max * _TABLE_LINE_HEIGHT_MULT + 2 * _ROW_MARGIN_MAX
    k_total = k_header + n_rows * k_row

    scale = min(1.0, area_pt / k_total) if k_total else 1.0
    rows_that_fit = n_rows
    if scale < _TABLE_SCALE_FLOOR:
        scale = _TABLE_SCALE_FLOOR
        usable = area_pt / scale - k_header
        rows_that_fit = max(1, min(n_rows, int(usable // k_row))) if k_row else n_rows

    return header_font_max * scale, body_font_max * scale, _ROW_MARGIN_MAX * scale, rows_that_fit

_POSITIVE_RGB = RGBColor(0x1E, 0x8E, 0x5A)
_NEGATIVE_RGB = RGBColor(0xC2, 0x3B, 0x3B)
_NOMINAL_RGB = RGBColor(0x33, 0x33, 0x33)
_MUTED_RGB = RGBColor(0xAA, 0xAA, 0xAA)
_HEADER_RGB = RGBColor(0x22, 0x22, 0x22)

# legenda da tabela de variacao, reaproveitada tanto na tela (app.py)
# quanto aqui no PowerPoint - fonte unica pra nao duplicar a redacao.
# Duas versoes: com participacao (indicadores aditivos, ver
# INDICATORS[...]["additive"] em app.py - a 2a linha de cada celula e a
# variacao de MS) e sem (ex.: Preco Medio, onde MS nao faz sentido e a
# celula so tem a 1a linha).
TABLE_LEGEND_WITH_SHARE = "1º número: variação % do indicador • 2º número: variação da participação (share) no total, em p.p."
TABLE_LEGEND_NO_SHARE = "Número: variação % do indicador no período."


def _add_variation_paragraph(paragraph, value, suffix, nominal_text, font_size):
    """Preenche um paragrafo com a variacao colorida (seta + %/pp) seguida
    do valor nominal em cinza escuro entre parenteses - mesma convencao de
    `app._variation_span`."""
    if value is None:
        run = paragraph.add_run()
        run.text = "–"
        run.font.name = _FONT_NAME
        run.font.color.rgb = _MUTED_RGB
        run.font.size = font_size
        return
    color = _POSITIVE_RGB if value >= 0 else _NEGATIVE_RGB
    icon = "▲" if value >= 0 else "▼"
    run = paragraph.add_run()
    run.text = f"{icon} {value:+.1f}{suffix}"
    run.font.name = _FONT_NAME
    run.font.color.rgb = color
    run.font.size = font_size
    if nominal_text is not None:
        run2 = paragraph.add_run()
        run2.text = f" ({nominal_text})"
        run2.font.name = _FONT_NAME
        run2.font.color.rgb = _NOMINAL_RGB
        run2.font.size = font_size


def _fill_variation_cell(cell, pct, share_pp, nominal, share_value, value_decimals, show_share, font_size):
    tf = cell.text_frame
    tf.word_wrap = True
    nominal_text = f"{nominal:,.{value_decimals}f}" if nominal is not None else None
    _add_variation_paragraph(tf.paragraphs[0], pct, "%", nominal_text, font_size)
    if show_share:
        share_text = f"{share_value:.1f}%" if share_value is not None else None
        p = tf.add_paragraph()
        _add_variation_paragraph(p, share_pp, "pp", share_text, font_size)


_BODY_FILL_RGB = RGBColor(0xFF, 0xFF, 0xFF)


def _style_table_plain(table, n_rows, n_cols, margin_pt=2.0):
    """Remove o banding/tema colorido padrao do PowerPoint pra tabela (fundo
    branco solido, cabecalho incluso) - o estilo padrao (faixas azuis
    alternadas, cabecalho colorido) nao existe na tabela HTML da tela,
    onde o cabecalho tambem e branco (so uma borda embaixo, sem fundo -
    ver `app._TABLE_CELL_STYLE`). `margin_pt` (topo/base de cada
    celula) encolhe junto com a fonte no scale-to-fit (ver `_fit_table`)
    - a margem esquerda/direita fica fixa, so a vertical conta pra
    altura da linha."""
    table.first_row = False
    table.horz_banding = False
    for i in range(n_rows):
        for j in range(n_cols):
            cell = table.cell(i, j)
            cell.fill.solid()
            cell.fill.fore_color.rgb = _BODY_FILL_RGB
            cell.margin_left = Pt(4)
            cell.margin_right = Pt(4)
            cell.margin_top = Pt(margin_pt)
            cell.margin_bottom = Pt(margin_pt)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE


def _fill_table(table, header, rows_data, value_decimals, show_share, header_size, body_size):
    for j, text in enumerate(header):
        cell = table.cell(0, j)
        cell.text = text
        run = cell.text_frame.paragraphs[0].runs[0]
        run.font.name = _FONT_NAME
        run.font.bold = True
        run.font.size = header_size
        run.font.color.rgb = _HEADER_RGB

    for i, (cat, cells) in enumerate(rows_data, start=1):
        cat_cell = table.cell(i, 0)
        cat_cell.text = cat
        cat_cell.text_frame.word_wrap = True
        cat_run = cat_cell.text_frame.paragraphs[0].runs[0]
        cat_run.font.name = _FONT_NAME
        cat_run.font.bold = True
        cat_run.font.size = body_size
        for j, (pct, share_pp, nominal, share_value) in enumerate(cells, start=1):
            _fill_variation_cell(
                table.cell(i, j), pct, share_pp, nominal, share_value, value_decimals, show_share, body_size,
            )


def _col_widths(total_width, n_year_cols, cat_width):
    year_width = Emu(int((total_width - cat_width) / max(n_year_cols, 1)))
    return [cat_width] + [year_width] * n_year_cols


def _chart_area_size():
    """(width, height) da caixa reservada pro grafico no slide 1 - fixa,
    independente da figura (o grafico e renderizado nessa mesma proporcao
    - ver `build_pptx` - entao sempre preenche a caixa inteira, sem
    letterboxing nem distorcao)."""
    usable_width = _SLIDE_WIDTH - 2 * _MARGIN
    chart_area_width = Emu(int(usable_width * _CHART_WIDTH_FRACTION))
    area_height = Emu(int(_CONTENT_BOTTOM - _CONTENT_TOP))
    return chart_area_width, area_height


def _picture_box(img_w_px, img_h_px, box_left, box_top, box_width, box_height):
    """(left, top, width, height) do maior retangulo que cabe em
    `box_width`x`box_height` mantendo a proporcao de `img_w_px`x`img_h_px`
    (contain), centralizado na caixa. Precisa ser "contain" (nao esticar
    pra preencher a caixa inteira): o grafico usa margens em PIXELS fixos
    (ver `alluvial_stack_chart`/`line_evolution_chart` - margin=dict(...)
    reservado pros rotulos de categoria/conectores a direita, pill de
    variacao em cima etc.) calibrados pra sua largura/altura originais
    (760 x fig.layout.height); forcar uma proporcao diferente na
    renderizacao (ex.: exportar num tamanho que combine com a caixa do
    slide) faz essas margens ocuparem uma fracao errada da imagem e
    rotulos/linhas ficam cortados ou fora do lugar."""
    aspect = img_w_px / img_h_px
    if box_width / box_height > aspect:
        height = box_height
        width = Emu(int(box_height * aspect))
    else:
        width = box_width
        height = Emu(int(box_width / aspect))
    left = Emu(int(box_left + (box_width - width) / 2))
    top = Emu(int(box_top + (box_height - height) / 2))
    return left, top, width, height


_HIGHLIGHT_BLOCK_HEIGHT = Inches(1.3)
_HIGHLIGHT_GAP = Inches(0.15)

# faixa reservada pra legenda da tabela (ver TABLE_LEGEND_WITH_SHARE/
# TABLE_LEGEND_NO_SHARE), logo abaixo da tabela - so na coluna da
# tabela, nao full-width (o grafico ao lado nao tem legenda)
_LEGEND_STRIP_HEIGHT = Inches(0.28)
_LEGEND_GAP = Inches(0.05)


def _add_table_legend(slide, left, top, width, legend_text):
    txbox = slide.shapes.add_textbox(left, top, width, _LEGEND_STRIP_HEIGHT)
    tf = txbox.text_frame
    tf.word_wrap = True
    run = tf.paragraphs[0].add_run()
    run.text = legend_text
    run.font.name = _FONT_NAME
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor(0x88, 0x88, 0x88)


def _add_highlight_textbox(slide, top, height, highlight_text):
    """Caixa de texto "Highlights" de largura cheia, abaixo do grafico/
    tabela - mesma posicao relativa (chart+tabela em cima, highlight
    embaixo) do bloco na tela (`app._chart_block`)."""
    text_width = _SLIDE_WIDTH - 2 * _MARGIN
    txbox = slide.shapes.add_textbox(_MARGIN, top, text_width, height)
    tf = txbox.text_frame
    tf.word_wrap = True

    heading_run = tf.paragraphs[0].add_run()
    heading_run.text = "Highlights"
    heading_run.font.name = _FONT_NAME
    heading_run.font.bold = True
    heading_run.font.size = Pt(14)
    heading_run.font.color.rgb = _HEADER_RGB

    body_p = tf.add_paragraph()
    body_p.space_before = Pt(4)
    body_run = body_p.add_run()
    body_run.text = highlight_text
    body_run.font.name = _FONT_NAME
    body_run.font.size = Pt(12)
    body_run.font.color.rgb = RGBColor(0x33, 0x33, 0x33)


def _add_combo_slide(prs, img_bytes, img_w_px, img_h_px, header, rows_data, value_decimals, show_share, highlight_text=None):
    """Slide com o grafico a esquerda e a tabela a direita - reproduz o
    layout da tela. Se `highlight_text` for passado, reserva uma faixa
    full-width embaixo pro texto de Highlights (mesma posicao relativa
    da tela). A tabela encolhe fonte/margem pra tentar caber `rows_data`
    inteira (scale-to-fit, ver `_fit_table`); o que nem assim couber e
    devolvido pro chamador colocar num slide de continuacao."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _add_logo(slide)
    _add_footer(slide)

    chart_area_width, full_area_height = _chart_area_size()
    if highlight_text:
        area_height = Emu(int(full_area_height - _HIGHLIGHT_BLOCK_HEIGHT - _HIGHLIGHT_GAP))
    else:
        area_height = full_area_height

    left, top, width, height = _picture_box(img_w_px, img_h_px, _MARGIN, _CONTENT_TOP, chart_area_width, area_height)
    slide.shapes.add_picture(BytesIO(img_bytes), left, top, width=width, height=height)

    table_left = _MARGIN + chart_area_width + _GAP
    table_width = _SLIDE_WIDTH - _MARGIN - table_left
    # a legenda fica so na coluna da tabela (o grafico ao lado nao tem
    # legenda) - reduz a altura disponivel pra tabela, nao pro grafico
    table_area_height = Emu(int(area_height - _LEGEND_STRIP_HEIGHT - _LEGEND_GAP))

    header_font, body_font, margin_pt, rows_that_fit = _fit_table(
        len(rows_data), table_area_height, show_share, _COMBO_HEADER_FONT_MAX, _COMBO_BODY_FONT_MAX,
    )
    shown_rows, overflow_rows = rows_data[:rows_that_fit], rows_data[rows_that_fit:]

    n_rows = len(shown_rows) + 1
    n_cols = len(header)
    graphic_frame = slide.shapes.add_table(n_rows, n_cols, table_left, _CONTENT_TOP, table_width, table_area_height)
    table = graphic_frame.table
    _style_table_plain(table, n_rows, n_cols, margin_pt)
    for i, col_width in enumerate(_col_widths(table_width, n_cols - 1, Inches(1.35))):
        table.columns[i].width = col_width
    _fill_table(table, header, shown_rows, value_decimals, show_share, Pt(header_font), Pt(body_font))

    legend_top = Emu(int(_CONTENT_TOP + table_area_height + _LEGEND_GAP))
    legend_text = TABLE_LEGEND_WITH_SHARE if show_share else TABLE_LEGEND_NO_SHARE
    _add_table_legend(slide, table_left, legend_top, table_width, legend_text)

    if highlight_text:
        text_top = Emu(int(_CONTENT_TOP + area_height + _HIGHLIGHT_GAP))
        _add_highlight_textbox(slide, text_top, _HIGHLIGHT_BLOCK_HEIGHT, highlight_text)
    return slide, overflow_rows


def _add_table_slide(prs, header, rows_data, value_decimals, show_share):
    """Slide de continuacao (so tabela, largura cheia) pro que nao coube
    no slide 1 junto com o grafico - mesmo scale-to-fit de
    `_add_combo_slide` (teto de fonte maior, ver `_FULL_HEADER_FONT_MAX`/
    `_FULL_BODY_FONT_MAX`: mais espaco por ter a largura toda so pra
    tabela). O que nem assim couber e devolvido pro chamador colocar em
    MAIS um slide de continuacao (`build_pptx` chama em loop ate
    esvaziar)."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _add_logo(slide)
    _add_footer(slide)
    width = _SLIDE_WIDTH - 2 * _MARGIN
    full_area_height = Emu(int(_CONTENT_BOTTOM - _CONTENT_TOP))
    table_area_height = Emu(int(full_area_height - _LEGEND_STRIP_HEIGHT - _LEGEND_GAP))

    header_font, body_font, margin_pt, rows_that_fit = _fit_table(
        len(rows_data), table_area_height, show_share, _FULL_HEADER_FONT_MAX, _FULL_BODY_FONT_MAX,
    )
    shown_rows, overflow_rows = rows_data[:rows_that_fit], rows_data[rows_that_fit:]

    n_rows = len(shown_rows) + 1
    n_cols = len(header)
    graphic_frame = slide.shapes.add_table(n_rows, n_cols, _MARGIN, _CONTENT_TOP, width, table_area_height)
    table = graphic_frame.table
    _style_table_plain(table, n_rows, n_cols, margin_pt)
    for i, col_width in enumerate(_col_widths(width, n_cols - 1, Inches(2.8))):
        table.columns[i].width = col_width
    _fill_table(table, header, shown_rows, value_decimals, show_share, Pt(header_font), Pt(body_font))

    legend_top = Emu(int(_CONTENT_TOP + table_area_height + _LEGEND_GAP))
    legend_text = TABLE_LEGEND_WITH_SHARE if show_share else TABLE_LEGEND_NO_SHARE
    _add_table_legend(slide, _MARGIN, legend_top, width, legend_text)
    return slide, overflow_rows


def build_pptx(
    fig: go.Figure,
    categories: list[str],
    values: dict[str, dict[str, float]],
    additive: bool,
    value_decimals: int,
    totals_override: dict[str, float] | None = None,
    highlight_text: str | None = None,
) -> bytes:
    prs = Presentation()
    prs.slide_width = _SLIDE_WIDTH
    prs.slide_height = _SLIDE_HEIGHT

    # renderiza na proporcao ORIGINAL do grafico (760 - largura padrao dos
    # dois construtores de grafico em charts.py, sempre usada aqui - x a
    # altura de verdade, preservada em fig.layout.height mesmo depois do
    # app zerar fig.layout.width pra autosize) - as margens dos graficos
    # sao em pixels fixos, calibradas pra essa proporcao especificamente
    # (rotulos de categoria/conectores a direita, pill de variacao em
    # cima etc.); exportar numa proporcao diferente (ex.: pra bater com a
    # caixa do slide) faz as margens ocuparem uma fracao errada da imagem
    # e rotulos/linhas saem cortados ou fora do lugar - por isso o
    # encaixe na caixa do slide e "contain" (ver `_picture_box`), nao
    # esticado
    img_w_px = 760
    img_h_px = int(fig.layout.height or 640)
    img_bytes = fig.to_image(format="png", width=img_w_px, height=img_h_px, scale=3)

    header: list[str] = []
    rows_data: list[tuple[str, list]] = []
    if categories:
        variations = compute_variations(values, categories, YEARS_DEFAULT, additive, totals_override)
        year_pairs = [(YEARS_DEFAULT[i][1:], YEARS_DEFAULT[i + 1][1:]) for i in range(len(YEARS_DEFAULT) - 1)]
        header = ["Categoria"] + [f"{y0}→{y1}" for y0, y1 in year_pairs]
        rows_data = [
            (
                cat,
                [
                    (
                        variations[cat]["pct"][i],
                        variations[cat]["share_pp"][i],
                        variations[cat]["nominal"][i],
                        variations[cat]["share_value"][i],
                    )
                    for i in range(len(year_pairs))
                ],
            )
            for cat in categories
        ]

    _, overflow_rows = _add_combo_slide(
        prs, img_bytes, img_w_px, img_h_px, header, rows_data, value_decimals, additive, highlight_text,
    )
    while overflow_rows:
        _, overflow_rows = _add_table_slide(prs, header, overflow_rows, value_decimals, additive)

    buf = BytesIO()
    prs.save(buf)
    return buf.getvalue()


def build_price_unit_pptx(charts: list[tuple[go.Figure, str]]) -> bytes:
    """Exportacao da aba "Price/Unit": um slide por categoria, grafico
    (waterfall) a esquerda e o texto de Highlights a direita - mesmo
    layout/proporcao de `_add_combo_slide`, so com um texto simples no
    lugar da tabela (essa aba nao tem tabela de variacao). `charts`: uma
    entrada (fig, texto_highlight) por categoria, na mesma ordem exibida
    na tela."""
    prs = Presentation()
    prs.slide_width = _SLIDE_WIDTH
    prs.slide_height = _SLIDE_HEIGHT

    chart_area_width, area_height = _chart_area_size()
    text_left = _MARGIN + chart_area_width + _GAP
    text_width = _SLIDE_WIDTH - _MARGIN - text_left

    for fig, highlight_text in charts:
        img_w_px = 760
        img_h_px = int(fig.layout.height or 460)
        img_bytes = fig.to_image(format="png", width=img_w_px, height=img_h_px, scale=3)

        slide = prs.slides.add_slide(prs.slide_layouts[6])
        _add_logo(slide)
        _add_footer(slide)
        left, top, width, height = _picture_box(img_w_px, img_h_px, _MARGIN, _CONTENT_TOP, chart_area_width, area_height)
        slide.shapes.add_picture(BytesIO(img_bytes), left, top, width=width, height=height)

        txbox = slide.shapes.add_textbox(text_left, _CONTENT_TOP, text_width, area_height)
        tf = txbox.text_frame
        tf.word_wrap = True

        heading_run = tf.paragraphs[0].add_run()
        heading_run.text = "Highlights"
        heading_run.font.name = _FONT_NAME
        heading_run.font.bold = True
        heading_run.font.size = Pt(16)
        heading_run.font.color.rgb = _HEADER_RGB

        body_p = tf.add_paragraph()
        body_p.space_before = Pt(8)
        body_run = body_p.add_run()
        body_run.text = highlight_text
        body_run.font.name = _FONT_NAME
        body_run.font.size = Pt(13)
        body_run.font.color.rgb = RGBColor(0x33, 0x33, 0x33)

    buf = BytesIO()
    prs.save(buf)
    return buf.getvalue()
