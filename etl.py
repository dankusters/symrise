"""ETL: le a planilha Worldpanel e monta um dataframe (formato wide) com
uma coluna por indicador+ano (ex.: volume_Y2022), pronto para os graficos.

Regras aplicadas (decididas em conjunto com o usuario, ver ESCOPO.md):
1. A coluna G ("Marcas") e tratada como rotulo descritivo da hierarquia
   (Cod.), nao como dimensao de filtro.
2. Indicadores percentuais nao tem a mesma escala na planilha:
   - "Share Unidades" e "Share Valor com Presentes %" vem como fracao
     (0-1) e sao convertidos para pontos percentuais (x100).
   - "Penetracao" ja vem em escala percentual e e mantida como esta.
3. "Frequencia" nao e percentual (apesar do texto do escopo dizer isso);
   e mantida como valor decimal simples.
"""

from __future__ import annotations

import re

import pandas as pd

SOURCE_PATH = "fonte/Vfinal_2026.07.06_Symrise_Worldpanel.xlsx"
SHEET_NAME = "Relatório Completo"

CATEGORY_COLUMNS = {
    "Região": "regiao",
    "Segmento": "segmento",
    "Fabricante": "fabricante",
    "Marca": "marca",
    "Classificação": "classificacao",
    "Cód.": "cod",
    "Marcas": "rotulo",
}

INDICATOR_SLUGS = {
    "Volume (lts)": "volume",
    "Unidades (absoluto)": "unidades",
    "Share Unidades": "share_unidades",
    "Valor sem Presentes (R$)": "valor_sem_presentes",
    "Valor com Presentes (R$)": "valor_com_presentes",
    "Share Valor com Presentes %": "share_valor_com_presentes",
    "Compradores": "compradores",
    "Penetração": "penetracao",
    "Vol. por Comprador": "vol_por_comprador",
    "Frequência": "frequencia",
    "Preço Médio (Litros)": "preco_medio_litros",
    "Preço Médio (Unidades)": "preco_medio_unidades",
}

# indicadores que vem como fracao (0-1) na planilha e precisam de x100
FRACTION_TO_PERCENT = {"share_unidades", "share_valor_com_presentes"}

# indicadores nominais inteiros
INTEGER_INDICATORS = {"unidades", "valor_sem_presentes", "valor_com_presentes", "compradores"}

# demais indicadores numericos: mantidos com 1 casa decimal
ONE_DECIMAL_INDICATORS = {
    "volume",
    "share_unidades",
    "share_valor_com_presentes",
    "penetracao",
    "vol_por_comprador",
    "frequencia",
    "preco_medio_litros",
    "preco_medio_unidades",
}

# correcao de nomes de marca com hifen colado (ex.: "O. Muriel-Cf" -> "O. Muriel - Cf")
_MARCA_FIX_PATTERN = re.compile(r"-(C[a-zA-Z]{1,3})$")


def _fix_marca(value: str) -> str:
    return _MARCA_FIX_PATTERN.sub(r" - \1", value)


# colunas reais de dados na planilha: A-G (categorias) + 12 indicadores x 4 anos
NUM_DATA_COLUMNS = len(CATEGORY_COLUMNS) + len(INDICATOR_SLUGS) * 4


def load_raw(path: str = SOURCE_PATH, sheet_name: str = SHEET_NAME) -> pd.DataFrame:
    """Le a planilha com cabecalho combinado (linha 5 = grupo do indicador,
    linha 6 = ano/categoria) e retorna um dataframe com colunas planas.

    Restringe a leitura as colunas A:BC (as unicas com dados reais): o
    pandas propaga o cabecalho de header multi-linha para a direita, entao
    colunas vazias sobrando na planilha (BD em diante) herdam por engano o
    rotulo do ultimo indicador/ano real (ex.: vira um "Preco Medio
    (Unidades)_Y2025" duplicado) se nao forem descartadas antes.
    """
    df = pd.read_excel(path, sheet_name=sheet_name, header=[4, 5])
    # descarta colunas fantasma criadas pelo forward-fill do cabecalho
    # multi-linha do pandas sobre as colunas vazias sobrando na planilha
    df = df.iloc[:, :NUM_DATA_COLUMNS]

    # linha 5 (nivel 0) so tem valor na primeira coluna de cada indicador;
    # propaga para as demais colunas do mesmo grupo (Y2022..Y2025)
    level0 = pd.Series(df.columns.get_level_values(0)).ffill()
    level1 = pd.Series(df.columns.get_level_values(1))

    new_columns = []
    for group, sub in zip(level0, level1):
        sub = str(sub).strip()
        if sub in CATEGORY_COLUMNS:
            new_columns.append(CATEGORY_COLUMNS[sub])
        elif group in INDICATOR_SLUGS:
            new_columns.append(f"{INDICATOR_SLUGS[group]}_{sub}")
        else:
            new_columns.append(None)  # colunas vazias sobrando na planilha

    df.columns = new_columns
    df = df.loc[:, [c for c in df.columns if c is not None]]
    df = df.dropna(how="all")
    return df


def build_dataset(path: str = SOURCE_PATH, sheet_name: str = SHEET_NAME) -> pd.DataFrame:
    """Monta o dataframe final (wide), com tipos e escalas corrigidos."""
    df = load_raw(path, sheet_name)

    # Cod. como string (evita perder "4.10" para 4.1 como float)
    df["cod"] = df["cod"].astype(str).str.strip()

    for col in ("regiao", "segmento", "fabricante", "marca", "classificacao", "rotulo"):
        df[col] = df[col].astype(str).str.strip()

    df["marca"] = df["marca"].map(_fix_marca)

    # "We Pink" (ramo agregado por segmento='Total') e "WePink" (ramo por
    # segmento real) sao o mesmo fabricante/marca grafado diferente
    # (ver ESCOPO.md); padroniza como "WePink" pra nao aparecerem como
    # entidades separadas em filtros/quebras
    for col in ("fabricante", "marca"):
        df[col] = df[col].replace("We Pink", "WePink")

    indicator_cols = [c for c in df.columns if c not in CATEGORY_COLUMNS.values()]
    # "-" e o placeholder da planilha para indicadores calculados sem base
    # (ex.: divisao por zero em Vol. por Comprador/Frequencia/Preco Medio)
    df[indicator_cols] = df[indicator_cols].replace("-", 0)
    df[indicator_cols] = df[indicator_cols].apply(pd.to_numeric, errors="raise")
    df[indicator_cols] = df[indicator_cols].fillna(0)

    for slug in FRACTION_TO_PERCENT:
        year_cols = [c for c in indicator_cols if c.startswith(f"{slug}_Y")]
        df[year_cols] = df[year_cols] * 100

    for slug in ONE_DECIMAL_INDICATORS:
        year_cols = [c for c in indicator_cols if c.startswith(f"{slug}_Y")]
        df[year_cols] = df[year_cols].round(1)

    for slug in INTEGER_INDICATORS:
        year_cols = [c for c in indicator_cols if c.startswith(f"{slug}_Y")]
        df[year_cols] = df[year_cols].round(0).astype("int64")

    return df.reset_index(drop=True)


if __name__ == "__main__":
    dataset = build_dataset()
    print(dataset.shape)
    print(dataset.head())
