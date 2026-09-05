"""
Dicionario de cores por entidade (Fabricante, Marca, Regiao, Segmento).

BRAND_COLORS e SEGMENT_COLORS sao PLACEHOLDER: cores geradas
aleatoriamente (seed fixa) apenas para desenvolvimento. Devem ser
substituidas pelos valores oficiais de identidade visual quando
disponibilizados. Mantido em arquivo separado para facil edicao manual.

REGION_COLORS ja usa valores reais, extraidos por amostragem de pixel da
imagem de referencia do escopo (fonte/"exemplo sankey e alluvium.png").

Uso: import e chame get_color(nome) para obter a cor de qualquer marca,
fabricante, sub-marca, variante, regiao ou segmento.

Observacao: a planilha usa "Giovanna baby" na coluna Fabricante e
"Giovanna Baby" na coluna Marca (mesma marca, capitalizacao diferente) -
unificadas aqui numa unica entrada; a busca em get_color() e
case-insensitive para nao quebrar caso outra variante de capitalizacao
apareca na base.
"""

import zlib

BRAND_COLORS: dict[str, str] = {
    "Athenas Industrias": "#8D255E",
    "Avatim": "#29AE55",
    "Avon": "#B2CC3E",
    "Baruel": "#D4A421",
    "Bebe Natureza": "#92462A",
    "Betulla": "#4CD035",
    "Betulla Cosmeticos": "#C841B6",
    "Boticário": "#63E029",
    "Chimica Baruel": "#2F73CA",
    "Ciclo Cosméticos": "#912190",
    "Coty": "#8AC125",
    "Eudora": "#2BA658",
    "Flora": "#289586",
    "Giovanna Baby": "#319AB9",
    "Giovanna Baby - Cf": "#1DBFB4",
    "Giovanna Baby Classic - Cli": "#D96E30",
    "Giovanna Baby Giby Borbolet.": "#979E1F",
    "Granado": "#D638AC",
    "Granado Bebê": "#4E9027",
    "Hinode": "#B62B5E",
    "Jequiti": "#9D7525",
    "Johnson": "#2EA7CC",
    "Kanitz": "#A92371",
    "Kenvue": "#2499AE",
    "Korres": "#D5446D",
    "Lattafa": "#E19D37",
    "Mahogany": "#73B81E",
    "Mary Kay": "#8BCB25",
    "Muriel": "#29E060",
    "Natura": "#309720",
    "Natura&CO": "#39B332",
    "O. Muriel - Cf": "#23689A",
    "O. U. I": "#40C71F",
    "Outras": "#46DF20",
    "Outros Fabricante": "#1F96DB",
    "Outros Fabricantes": "#87A225",
    "P&G": "#2CDD3E",
    "Phebo": "#21D44B",
    "Phytoderm": "#BF27C4",
    "Poran": "#4CCC38",
    "Quem Disse Berenice": "#3C2790",
    "Quimetal": "#D0C749",
    "Rugol": "#A2D93A",
    "Suissa": "#C87D28",
    "Turma da Xuxa - Cli": "#199A2A",
    "WePink": "#1DC94B",
}


# Cores de Regiao: extraidas por amostragem de pixel da imagem de
# referencia (fonte/"exemplo sankey e alluvium.png"), que e a fonte oficial
# do "layout de cores" pedido no escopo para os graficos de evolucao.
# As 4 regioes-pai (que somam T. Brasil) usam a cor exata da imagem; as
# sub-regioes de Sudeste usam tons derivados da mesma familia (navy).
REGION_COLORS: dict[str, str] = {
    "N+NE": "#1D7299",
    "Sudeste": "#142355",
    "C.Oeste": "#D79BAA",
    "Sul": "#FC6C6A",
    "Gde RJ": "#2A3F7A",
    "Gde SP": "#3B5296",
    "Int.SP": "#4C66B2",
    "Leste+IRJ": "#1A2C66",
    "T. Brasil": "#4A4A4A",
}

# Cores de Segmento: PLACEHOLDER (nao ha referencia oficial ainda).
SEGMENT_COLORS: dict[str, str] = {
    "Feminino": "#D6336C",
    "Masculino": "#1971C2",
    "Infantil": "#F08C00",
    "Unisex": "#37B24D",
    "Total": "#495057",
}

_LOOKUP = {
    name.lower(): hexcolor
    for source in (BRAND_COLORS, REGION_COLORS, SEGMENT_COLORS)
    for name, hexcolor in source.items()
}


def get_color(name: str) -> str:
    """Retorna a cor cadastrada para a entidade (busca case-insensitive);
    gera uma cor estavel (hash-based) como fallback para nomes ainda nao
    cadastrados (ex.: sub-marcas e variantes)."""
    hit = _LOOKUP.get(name.lower())
    if hit is not None:
        return hit
    digest = zlib.crc32(name.encode("utf-8"))
    h = digest % 360
    return hsl_to_hex(h, 65, 45)


def hsl_to_hex(h: int, s: int, l: int) -> str:
    """Conversao HSL -> hex (h: 0-360, s/l: 0-100)."""
    s /= 100
    l /= 100
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = l - c / 2
    if h < 60:
        r, g, b = c, x, 0
    elif h < 120:
        r, g, b = x, c, 0
    elif h < 180:
        r, g, b = 0, c, x
    elif h < 240:
        r, g, b = 0, x, c
    elif h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x
    r, g, b = [round((v + m) * 255) for v in (r, g, b)]
    return f"#{r:02X}{g:02X}{b:02X}"
