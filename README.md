# Symrise — Dashboard Worldpanel

Dashboard interativo (Plotly + Dash) da evolução anual (Y2022–Y2025) dos
indicadores de mercado de perfumaria no Brasil, a partir do relatório
Worldpanel (Kantar), com filtros combináveis de Região, Segmento,
Fabricante e Marca. Ver `ESCOPO.md` para o briefing original.

## Rodar localmente

```bash
pip install pandas openpyxl plotly kaleido dash
python app.py
```

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
  Fabricante, Marca, sub-marca, variante, Região ou Segmento (busca
  case-insensitive, com fallback determinístico por hash para nomes não
  cadastrados). Região usa cores reais extraídas por amostragem de pixel
  da imagem de referência do escopo; Fabricante/Marca/Segmento **ainda
  são placeholder aleatório** — substituir quando a paleta oficial
  chegar.

- **`charts.py`** — dois templates de gráfico:
  - `alluvial_stack_chart` — barras empilhadas por ano com fluxo curvo
    (cor rebaixada) entre elas, seta em "chave" mostrando a variação %
    ano a ano do total. Para indicadores cumulativos: Volume, Unidades,
    Valor (com/sem presentes), Compradores, Share Unidades, Share Valor
    com Presentes.
  - `line_evolution_chart` — uma linha por categoria, sem empilhamento.
    Para indicadores de taxa/média: Penetração, Vol. por Comprador,
    Frequência, Preço Médio (Litros/Unidades).
  - `compute_values(...)` — helper compartilhado que os dois templates
    (e `insights.py`) usam para extrair `{categoria: {ano: valor}}` de
    um DataFrame já filtrado.

- **`insights.py`** — `generate_insight(...)`: comentário automático
  (texto puro, sem IA generativa) que descreve a trajetória de cada
  categoria no último ano — crescimento/recuo comparado ao mercado
  total, ganho/perda de participação em pontos percentuais (MS), e
  aproximação entre categorias de participação parecida que estão
  divergindo. Roda sobre os mesmos dados do gráfico, então num filtro
  novo o texto muda junto.

- **`app.py`** — app Dash: dropdowns de Indicador, Quebra (Região /
  Segmento / Fabricante / Marca) e filtros fixos para as dimensões que
  não estão sendo usadas como quebra. Fabricante/Marca com muitas
  categorias usam top 6 + grupo sintético "Outros" (a diferença entre o
  total real e a soma dos 6 maiores, para as barras sempre fecharem
  100%).

## Status atual

**Feito:**
- ETL validado (5.742 linhas, 55 colunas)
- Os 12 indicadores do escopo cobertos pelos dois templates de gráfico
- Comentário automático (highlights) por categoria
- Filtros combináveis de Região/Segmento/Fabricante/Marca, com quebra
  dinâmica e agrupamento "Outros" para Fabricante/Marca

**Em aberto:**
- Paleta de cores oficial de Marca/Fabricante/Segmento (hoje placeholder
  aleatório em `colors.py`)
- Share Unidades / Share Valor com Presentes só funcionam quebrados por
  Segmento — a relação pai/filho do `Cód.` para esses dois indicadores
  ainda não foi resolvida para quebra por Fabricante/Marca
- Exportação para PDF/PPTX em múltiplas folhas A4 ou slides (ESCOPO.md
  seção 5)
- Estilo visual do app Dash (hoje HTML padrão do Dash + fonte Roboto via
  `assets/fonts.css`, sem CSS customizado além disso)
- Deploy/hospedagem do app fora do ambiente local
