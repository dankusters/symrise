# Symrise — Dashboard Worldpanel

Dashboard interativo (Plotly + Dash) da evolução anual (Y2022–Y2025) dos
indicadores de mercado de perfumaria no Brasil, a partir do relatório
Worldpanel (Kantar). Filtros combináveis de Região, Segmento,
Fabricante, Marca, Submarca, Variante e Sub Variante, mais duas árvores
à parte (Embalagem: Tipo e Conteúdo) que só combinam com Região. Ver
`ESCOPO.md` para o briefing original — bastante coisa no app hoje vai
além dele (Sub Variante, Embalagem, Price/Unit, Adições de Unidades),
descoberta/pedida ao longo do desenvolvimento.

## Rodar localmente

Projeto usa [uv](https://docs.astral.sh/uv/):

```bash
uv sync
uv run python app.py
```

(ou `pip install -e .` a partir do `pyproject.toml` num venv próprio,
depois `python app.py`)

Abre em `http://127.0.0.1:8050/`.

## Estrutura do código

- **`etl.py`** — lê `fonte/Vfinal_2026.07.06_Symrise_Worldpanel.xlsx`
  (aba "Relatório Completo") e monta um DataFrame *wide* via
  `build_dataset()`: uma linha por combinação de categorias, uma coluna
  por indicador+ano (`volume_Y2022`, `unidades_Y2023`, ...). Trata o
  cabeçalho combinado (grupo do indicador + ano), corrige a escala de
  `share_unidades`/`share_valor_com_presentes` (vêm como fração 0–1 na
  planilha, convertidas para pontos percentuais), o placeholder `"-"`
  (indicador sem base de cálculo → 0) e nomes de marca com hífen colado
  (ex.: `"O. Muriel-Cf"` → `"O. Muriel - Cf"`).

- **`colors.py`** — `get_color(nome)` retorna a cor de qualquer
  Fabricante, Marca, Sub Marca, Variante, Sub Variante, Embalagem,
  Segmento ou Região (busca case-insensitive, com fallback determinístico
  por hash para nomes não cadastrados). Região usa cores reais extraídas
  por amostragem de pixel da imagem de referência do escopo; as demais
  vêm de `fonte/hexa_colors.xlsx` (aba "2025"), a paleta oficial — é lida
  a cada carregamento, então editar o hexa na planilha reflete direto no
  dashboard, sem mexer em código.

- **`charts.py`** — templates de gráfico, todos com borda preta fina
  nas barras (`_BAR_BORDER_COLOR`/`_BAR_BORDER_WIDTH`):
  - `alluvial_stack_chart` — barras empilhadas por ano com fluxo curvo
    (cor rebaixada) entre elas. A ordem empilhada (topo → base) é
    recalculada ANO A ANO pelo próprio valor de cada categoria (maior
    sempre no topo) — duas categorias podem trocar de posição de um ano
    pro outro, cruzando o fluxo alluvial entre elas. Topo de cada
    coluna mostra o total (+ variação % ano a ano) quando as categorias
    somam o total de verdade, ou a soma da participação (`coverage_pct`,
    com a "chave" em pontos percentuais) quando é só um recorte top N
    (Marca/Submarca/Variante/Sub Variante). Para indicadores
    cumulativos: Volume, Unidades, Valor (com/sem presentes),
    Compradores, Share Unidades, Share Valor com Presentes.
  - `line_evolution_chart` — uma linha por categoria, sem empilhamento,
    sem rótulo de valor por ponto (a tabela ao lado já traz os
    números). Eixo Y com autorange normal (aceita negativos) e linha de
    referência em zero. Para indicadores de taxa/média: Penetração,
    Vol. por Comprador, Frequência, Preço Médio (Litros/Unidades), e a
    aba "Adições de Unidades".
  - `price_unit_waterfall_chart`/`price_unit_effects` — waterfall da
    decomposição Unidades × Preço Médio da aba "Price/Unit" (ver
    `app.py` abaixo).
  - `compute_values(...)` — helper compartilhado que os templates (e
    `insights.py`) usam para extrair `{categoria: {ano: valor}}` de um
    DataFrame já filtrado.

- **`insights.py`** — `generate_insight(...)`: comentário automático
  (texto puro, sem IA generativa) que descreve a trajetória de cada
  categoria no último ano — crescimento/recuo comparado ao mercado
  total, ganho/perda de participação em pontos percentuais (MS), e
  aproximação entre categorias de participação parecida que estão
  divergindo. Roda sobre os mesmos dados do gráfico, então num filtro
  novo o texto muda junto. `generate_price_unit_insight(...)` faz o
  mesmo pra aba Price/Unit (atribui o crescimento/queda do Valor a cada
  efeito, Unidades ou Preço).

- **`app.py`** — app Dash: abas de Região no topo, dropdown "Quebra
  por" (Segmento / Fabricante / Marca / Submarca / Variante / Sub
  Variante / Embalagem Tipo / Embalagem Conteúdo) e filtros em cascata
  (Segmento independente; Fabricante → Marca → Submarca/Variante/Sub
  Variante) fixos pras dimensões que não estão sendo usadas como
  quebra. Marca/Submarca/Variante/Sub Variante com muitas categorias
  usam um seletor de top N (10/20/30), sem grupo sintético "Outros" (o
  top N é só um recorte, não fecha 100% — daí o `coverage_pct` no
  gráfico). Fabricante usa top 6 + "Outros" (fecha o total real).
  Abas de indicador: Volume / Unidades / Valor com Presentes / Preço
  Médio (gráfico + tabela de variação + legenda + Highlights, um bloco
  por indicador) mais duas abas à parte:
  - **Price/Unit** — um waterfall por categoria decompondo a variação
    do Valor com Presentes em efeito Unidades × efeito Preço Médio;
    waterfall totalizador (soma de todas as categorias) no topo quando
    a quebra é Segmento ou Fabricante.
  - **Adições de Unidades** — uma linha por categoria com a diferença
    de Unidades ano a ano (2022 é a diferença sobre um zero artificial,
    já que a planilha não tem 2021), ordenada pela maior adição em
    2025; tabela ao lado com os mesmos números.

- **`export_pptx.py`** — exporta qualquer bloco (gráfico + tabela) ou a
  aba Price/Unit pra PowerPoint, com os MESMOS números da tela
  (reaproveita `compute_variations`/os `dict`s de valores já
  calculados). Logo Symrise + "Worldpanel Dashboard" no canto superior
  esquerdo e rodapé com a fonte dos dados em todo slide; fonte Roboto
  Condensed; tabela com "scale to fit" (encolhe fonte/margem pra caber
  num único slide, com piso legível — o que não couber nem assim
  transborda pra slide de continuação).

## Status atual

**Feito:**
- ETL validado (5.742 linhas, 55 colunas)
- Os 12 indicadores do escopo cobertos pelos templates de gráfico, mais
  a decomposição Unidades×Preço (Price/Unit) e as adições de Unidades
  ano a ano
- Comentário automático (highlights) por categoria/waterfall
- Filtros combináveis de Região/Segmento/Fabricante/Marca/Submarca/
  Variante/Sub Variante, com quebra dinâmica; duas quebras à parte de
  Embalagem (Tipo/Conteúdo), descobertas na planilha e não documentadas
  no ESCOPO.md — só combinam com Região
- Exportação PowerPoint (não PDF) com identidade visual Symrise, fiel
  aos números da tela
- Paleta de cores oficial de Fabricante/Marca/Sub Marca/Variante/Sub
  Variante/Embalagem/Segmento, lida direto de `fonte/hexa_colors.xlsx`

**Em aberto:**
- Share Unidades / Share Valor com Presentes só funcionam quebrados por
  Segmento — a relação pai/filho do `Cód.` para esses dois indicadores
  ainda não foi resolvida para quebra por Fabricante/Marca
- Exportação em múltiplas folhas A4 (PDF) — hoje só PowerPoint
  (ESCOPO.md seção 5)
- Deploy/hospedagem do app fora do ambiente local
