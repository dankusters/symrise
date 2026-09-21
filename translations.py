"""
Dicionario central de traducao PT->EN dos rotulos/categorias exibidos no
dashboard (dimensoes, indicadores e valores de categoria que NAO sao nomes
proprios). Edite/inclua/substitua entradas aqui conforme pedidos de ajuste -
qualquer mudanca aqui reflete em todo o app (dropdowns, graficos, tabelas,
breadcrumbs, export PowerPoint) sem precisar mexer em outro arquivo.

NAO adicione aqui nomes proprios (Fabricante, Marca, Sub Marca, Variante,
Sub Variante - ex.: "Boticário", "Floratta", "Floratta-red"): esses devem
permanecer exatamente como vem da planilha. `translate()` ja trata isso
sozinho - qualquer termo que nao esteja no dicionario volta sem alteracao,
entao nomes proprios nunca cadastrados aqui simplesmente passam intactos.

Uso: `from translations import translate` e chame `translate(texto)` em
qualquer ponto que exiba um rotulo de dimensao/indicador/categoria vindo da
planilha. Comparacoes internas (filtros, joins, lookup de cor) continuam
usando o valor original em portugues - a traducao e so para exibicao.
"""

from __future__ import annotations

TRANSLATIONS: dict[str, str] = {
    # --- Dimensoes (fornecido) ---
    "Região": "Region",
    "Regiões": "Regions",
    "Fabricante": "Manufacturer",
    "Segmento": "Segment",
    "Marca": "Brand",
    "Marcas": "Brands",
    "Submarca": "Sub-brand",
    "Submarcas": "Sub-brands",
    "Sub Marca": "Sub-brand",  # classificacao interna (etl.py) - mesmo termo de "Submarca"
    "Variante": "SKU",
    "Variantes": "SKUs",
    # --- Dimensoes (proposto - ajuste se quiser outro termo) ---
    "Sub Variante": "Sub-SKU",
    "Sub Variantes": "Sub-SKUs",
    "Embalagem": "Packaging",
    "Embalagem (Tipo)": "Packaging (Type)",
    "Embalagem (Conteúdo)": "Packaging (Content)",

    # --- Valores de Segmento (fornecido) ---
    "Feminino": "Female",
    "Masculino": "Male",
    "Infantil": "Children",
    # --- Valor de Segmento nao mencionado (proposto) ---
    "Unisex": "Unisex",

    # --- Indicadores (fornecido) ---
    "Unidade": "Unit",
    "Unidades": "Units",
    "Valor com Presente": "Revenue",
    "Valor com Presentes": "Revenue",
    "Compradores": "Buyers",
    "Share Valor com Presente": "Revenue Share",
    "Share Valor com Presentes": "Revenue Share",
    "Frequência": "Frequency Rate",
    "Penetração": "Penetration Rate",
    "Vol. por Comprador": "Volume per Buyer",
    "Preço Médio (Unidades)": "Average Price per Unit",
    "Preço Médio (Litros)": "Average Price per Liter",
    # --- Indicadores nao mencionados (proposto) ---
    "Volume": "Volume",
    "Valor sem Presentes": "Revenue (excl. gifts)",
    "Share Unidades": "Units Share",

    # --- Regioes (proposto) ---
    "T. Brasil": "Total Brazil",
    "Sudeste": "Southeast",
    "C.Oeste": "Midwest",
    "Sul": "South",
    "N+NE": "North+Northeast",

    # --- Valores fixos de filtro (proposto) ---
    # "Outras"/"Demais outras"/"Demais Fabricantes"/"Não Body Splash" NAO
    # entram aqui: sao rotulos sinteticos criados pelo proprio app (nao
    # vem da planilha), ja em ingles direto na fonte (ver app.py/colors.py).
    "Total": "Total",
    "Sim": "Yes",
    "Não": "No",
    "Body Splash": "Body Splash",

    # --- Cabecalhos de tabela (proposto) ---
    "Categoria": "Category",
    "Produto": "Product",
    "Cód.": "Code",
    "De": "From",
    "Para": "To",
    "Ignorado?": "Ignored?",
}


def translate(text: str) -> str:
    """Traduz um rotulo/categoria; termos fora do dicionario (nomes proprios
    de Fabricante/Marca/Sub Marca/Variante/Sub Variante, entre outros)
    voltam inalterados."""
    return TRANSLATIONS.get(text, text)
