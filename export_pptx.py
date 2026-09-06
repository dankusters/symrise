"""Exportacao de um bloco (grafico + tabela de variacao) para PowerPoint:
slide 1 com o grafico ocupando o slide inteiro, slides seguintes com a
tabela de variacao (dividida em varios slides quando tem muitas linhas -
Marca/Submarca/Variante podem chegar a 30 categorias no top N).

Reaproveita `compute_variations` (mesma funcao usada pela tabela HTML do
app) pra garantir que os numeros exportados sejam identicos aos exibidos
na tela - so muda a camada de apresentacao (python-pptx em vez de Dash).
"""

from __future__ import annotations

from io import BytesIO

import plotly.graph_objects as go
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Emu, Inches, Pt

from charts import YEARS_DEFAULT, compute_variations

_SLIDE_WIDTH = Inches(13.333)
_SLIDE_HEIGHT = Inches(7.5)
_ROWS_PER_SLIDE = 15

_POSITIVE_RGB = RGBColor(0x1E, 0x8E, 0x5A)
_NEGATIVE_RGB = RGBColor(0xC2, 0x3B, 0x3B)
_NOMINAL_RGB = RGBColor(0x33, 0x33, 0x33)
_MUTED_RGB = RGBColor(0xAA, 0xAA, 0xAA)
_HEADER_RGB = RGBColor(0x22, 0x22, 0x22)


def _add_variation_paragraph(paragraph, value, suffix, nominal_text):
    """Preenche um paragrafo com a variacao colorida (seta + %/pp) seguida
    do valor nominal em cinza escuro entre parenteses - mesma convencao de
    `app._variation_span`."""
    if value is None:
        run = paragraph.add_run()
        run.text = "–"
        run.font.color.rgb = _MUTED_RGB
        run.font.size = Pt(11)
        return
    color = _POSITIVE_RGB if value >= 0 else _NEGATIVE_RGB
    icon = "▲" if value >= 0 else "▼"
    run = paragraph.add_run()
    run.text = f"{icon} {value:+.1f}{suffix}"
    run.font.color.rgb = color
    run.font.size = Pt(11)
    if nominal_text is not None:
        run2 = paragraph.add_run()
        run2.text = f" ({nominal_text})"
        run2.font.color.rgb = _NOMINAL_RGB
        run2.font.size = Pt(11)


def _fill_variation_cell(cell, pct, share_pp, nominal, share_value, value_decimals, show_share):
    tf = cell.text_frame
    tf.word_wrap = True
    nominal_text = f"{nominal:,.{value_decimals}f}" if nominal is not None else None
    _add_variation_paragraph(tf.paragraphs[0], pct, "%", nominal_text)
    if show_share:
        share_text = f"{share_value:.1f}%" if share_value is not None else None
        p = tf.add_paragraph()
        _add_variation_paragraph(p, share_pp, "pp", share_text)


def _add_table_slide(prs, header, rows_data, col_widths, value_decimals, show_share):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    n_rows = len(rows_data) + 1
    n_cols = len(header)
    left = Inches(0.4)
    top = Inches(0.4)
    width = _SLIDE_WIDTH - Inches(0.8)
    height = _SLIDE_HEIGHT - Inches(0.8)
    graphic_frame = slide.shapes.add_table(n_rows, n_cols, left, top, width, height)
    table = graphic_frame.table
    for i, col_width in enumerate(col_widths):
        table.columns[i].width = col_width

    for j, text in enumerate(header):
        cell = table.cell(0, j)
        cell.text = text
        run = cell.text_frame.paragraphs[0].runs[0]
        run.font.bold = True
        run.font.size = Pt(12)
        run.font.color.rgb = _HEADER_RGB

    for i, (cat, cells) in enumerate(rows_data, start=1):
        cat_cell = table.cell(i, 0)
        cat_cell.text = cat
        cat_run = cat_cell.text_frame.paragraphs[0].runs[0]
        cat_run.font.bold = True
        cat_run.font.size = Pt(11)
        for j, (pct, share_pp, nominal, share_value) in enumerate(cells, start=1):
            _fill_variation_cell(table.cell(i, j), pct, share_pp, nominal, share_value, value_decimals, show_share)
    return slide


def build_pptx(
    fig: go.Figure,
    categories: list[str],
    values: dict[str, dict[str, float]],
    additive: bool,
    value_decimals: int,
    totals_override: dict[str, float] | None = None,
) -> bytes:
    """{slide 1: grafico em tela cheia} + {slides seguintes: tabela de
    variacao, paginada em blocos de `_ROWS_PER_SLIDE` categorias}."""
    prs = Presentation()
    prs.slide_width = _SLIDE_WIDTH
    prs.slide_height = _SLIDE_HEIGHT

    img_bytes = fig.to_image(format="png", width=1920, height=1080, scale=2)
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.shapes.add_picture(BytesIO(img_bytes), Emu(0), Emu(0), width=_SLIDE_WIDTH, height=_SLIDE_HEIGHT)

    if categories:
        variations = compute_variations(values, categories, YEARS_DEFAULT, additive, totals_override)
        year_pairs = [(YEARS_DEFAULT[i][1:], YEARS_DEFAULT[i + 1][1:]) for i in range(len(YEARS_DEFAULT) - 1)]
        header = ["Categoria"] + [f"{y0}→{y1}" for y0, y1 in year_pairs]

        cat_col_width = Inches(2.8)
        year_col_width = Emu(int((_SLIDE_WIDTH - Inches(0.8) - cat_col_width) / max(len(year_pairs), 1)))
        col_widths = [cat_col_width] + [year_col_width] * len(year_pairs)

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
        for start in range(0, len(rows_data), _ROWS_PER_SLIDE):
            chunk = rows_data[start : start + _ROWS_PER_SLIDE]
            _add_table_slide(prs, header, chunk, col_widths, value_decimals, additive)

    buf = BytesIO()
    prs.save(buf)
    return buf.getvalue()
