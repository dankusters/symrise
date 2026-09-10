"""
Dicionario de cores por entidade (Fabricante, Marca, Sub Marca, Variante,
Sub Variante, Regiao, Segmento, Embalagem).

Fonte oficial: fonte/hexa_colors.xlsx, aba "2025" (colunas Fabricante/
Marca/Classificacao/Marcas/hexa). Essa planilha e a fonte de verdade das
cores - qualquer edicao nela (trocar um hexa, adicionar uma linha) passa
a valer no dashboard no proximo carregamento, sem mexer neste arquivo.
Deve ser mantida versionada no git.

A planilha usa "Marcas" (a mesma coluna G/"rotulo" da planilha principal,
ver etl.py) como rotulo descritivo de QUALQUER nivel da hierarquia - para
Sub Marca/Variante/Sub Variante ela bate exatamente com o nome usado nos
graficos, mas para Fabricante/Marca ela traz variantes prefixadas/
sufixadas (ex.: "T. Kenvue", "T. Kenvue-Cli") que nao existem como tal no
dataset: la, o grafico usa o nome puro (colunas "fabricante"/"marca").
Por isso, alem do lookup por "Marcas", indexamos tambem por essas duas
colunas para as linhas Classificacao == "Fabricante"/"Marca". Quando um
mesmo fabricante/marca tem mais de uma linha com hexa diferente (poucos
casos, ex.: "Kenvue"/"Poran"/"Quimetal"/"Rugol" - a planilha tem uma cor
pra cada quebra Cf/Cli/Cm), fica valendo a linha de rotulo mais curto (a
linha "T. <nome>" sem sufixo, a auto-total do fabricante/marca).

REGION_COLORS nao vem dessa planilha (ela nao cobre regiao): usa valores
reais, extraidos por amostragem de pixel da imagem de referencia do
escopo (fonte/"exemplo sankey e alluvium.png").

Uso: import e chame get_color(nome) para obter a cor de qualquer entidade
(fabricante, marca, sub-marca, variante, sub-variante, embalagem,
segmento ou regiao). A busca e case-insensitive.
"""

from __future__ import annotations

import re
import warnings
import zlib
from pathlib import Path

import openpyxl

HEXA_COLORS_PATH = Path(__file__).parent / "fonte" / "hexa_colors.xlsx"
HEXA_COLORS_SHEET = "2025"

# mesma correcao de nomes com hifen colado que etl.py aplica ao dataset
# principal (ex.: "Turma Da Xuxa-Cli" -> "Turma Da Xuxa - Cli"), pra nao
# perder o match entre a planilha de cores e o dataset por causa dessa
# inconsistencia de formatacao na fonte
_HYPHEN_SUFFIX_PATTERN = re.compile(r"-(C[a-zA-Z]{1,3})$")


def _fix_hyphen_suffix(value: str) -> str:
    return _HYPHEN_SUFFIX_PATTERN.sub(r" - \1", value)


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

# Rotulos sinteticos que a propria app.py cria (nao existem na planilha):
# o bucket "resto do ranking" de um top-N (_rank_top_n) e o "Total"
# generico. Cinza segue a mesma convencao da planilha oficial para
# linhas "Outros"/agregadoras; "Total" reusa o tom de "T. Brasil" acima.
_SYNTHETIC_COLORS: dict[str, str] = {
    "Outras": "#E0E0E0",
    "Demais outras": "#E0E0E0",
    "Total": "#4A4A4A",
}


def _load_official_colors(
    path: Path = HEXA_COLORS_PATH, sheet: str = HEXA_COLORS_SHEET
) -> dict[str, str]:
    """Le fonte/hexa_colors.xlsx e monta o lookup (nome em minusculas ->
    hexa) com as cores oficiais. Ver docstring do modulo para o motivo de
    indexar por 3 colunas diferentes."""
    try:
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    except (FileNotFoundError, OSError) as exc:
        warnings.warn(f"Nao foi possivel ler {path} ({exc}); usando fallback de cores.")
        return {}

    by_fabricante: dict[str, tuple[str, int]] = {}
    by_marca: dict[str, tuple[str, int]] = {}
    by_rotulo: dict[str, str] = {}

    for regiao, fabricante, marca, classificacao, rotulo, hexa, _cor in wb[sheet].iter_rows(
        min_row=2, values_only=True
    ):
        if not rotulo or not hexa:
            continue
        rotulo = str(rotulo).strip()
        by_rotulo.setdefault(rotulo.lower(), hexa)

        if classificacao == "Fabricante" and fabricante:
            key = _fix_hyphen_suffix(str(fabricante).strip()).lower()
            if key not in by_fabricante or len(rotulo) < by_fabricante[key][1]:
                by_fabricante[key] = (hexa, len(rotulo))
        elif classificacao == "Marca" and marca:
            key = _fix_hyphen_suffix(str(marca).strip()).lower()
            if key not in by_marca or len(rotulo) < by_marca[key][1]:
                by_marca[key] = (hexa, len(rotulo))

    return {
        **{k: v for k, (v, _) in by_fabricante.items()},
        **{k: v for k, (v, _) in by_marca.items()},
        **by_rotulo,
    }


_LOOKUP = {
    **{name.lower(): hexcolor for name, hexcolor in _SYNTHETIC_COLORS.items()},
    **_load_official_colors(),
    **{name.lower(): hexcolor for name, hexcolor in REGION_COLORS.items()},
}


def get_color(name: str) -> str:
    """Retorna a cor cadastrada para a entidade (busca case-insensitive);
    gera uma cor estavel (hash-based) como fallback para nomes ainda nao
    cadastrados em fonte/hexa_colors.xlsx."""
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
