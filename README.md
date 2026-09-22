# Symrise — Dashboard Worldpanel

Dashboard interativo (Plotly + Dash) da evolução anual (Y2022–Y2025) dos
indicadores de mercado de perfumaria no Brasil, a partir do relatório
Worldpanel (Kantar). Filtros combináveis de Região, Segmento,
Fabricante, Marca, Submarca, Variante, Sub Variante e IsBodySplash, mais
duas árvores à parte (Embalagem: Tipo e Conteúdo) que só combinam com
Região, e uma quebra à parte (Body Splash) que compara o crescimento de
Body Splash vs. o restante do mercado. Ver `ESCOPO.md` para o briefing
original — bastante coisa no app hoje vai além dele (Sub Variante,
Embalagem, Price/Unit, Adições de Unidades/Valor com Presentes, filtro
e quebra Body Splash), descoberta/pedida ao longo do desenvolvimento.

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
  dashboard, sem mexer em código. `contrast_text_color(hex)` escolhe
  texto preto/branco pelo brilho percebido (rótulo de valor dentro das
  barras empilhadas); `readable_foreground(hex)` escurece uma cor clara
  demais (preservando matiz/saturação) quando ela vira texto/linha sobre
  fundo branco (rótulo lateral do alluvial, linha do
  `line_evolution_chart`) — as duas cobrem tanto a paleta oficial quanto
  o fallback hash-based, sem precisar de coluna extra na planilha.

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
    Vol. por Comprador, Frequência, Preço Médio (Litros/Unidades).
  - `price_unit_waterfall_chart`/`price_unit_effects` — waterfall da
    decomposição Unidades × Preço Médio da aba "Price/Unit" (ver
    `app.py` abaixo).
  - `unit_additions_bridge_chart` — waterfall/"bridge" das abas
    "Adições de Unidades"/"Adições de Valor com Presente": dois pilares
    cinzas (total do indicador no penúltimo e no último ano) com um
    bloco por categoria entre eles (verde/vermelho conforme empurrou o
    total pra cima/baixo nessa única transição). Genérico por indicador
    — `app.py` reusa o mesmo template pras duas abas, só trocando os
    rótulos/unidade (ver `ADDITIONS_TABS` abaixo).
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
  efeito, Unidades ou Preço). `generate_unit_additions_insight(...)` faz
  o mesmo pras abas "Adições de X" (quem mais empurrou o total pra cima/
  baixo na transição 2024→2025) — `indicator_label`/`unit_label`
  parametrizam o texto por indicador (ex.: "O total de Unidades cresceu
  X milhões" vs. "O total de Valor com Presentes cresceu R$ X milhões" —
  unidades monetárias ficam com o "R$" antes do número, não depois).

- **`app.py`** — app Dash: abas de Região no topo (T. Brasil / Sudeste /
  C.Oeste / Sul / N+NE), mais uma aba extra, **Regiões**
  (`REGIOES_TAB_KEY`), que não fixa nenhuma região: quebra o escopo
  filtrado pelas 4 regiões reais (exclui T. Brasil, que é a soma delas —
  ver `REGIOES_BREAKDOWN_CATEGORIES`/`_regiao_root_values`). Só "Quebra
  por" fica desabilitado nessa aba (não há quebra por Segmento/
  Fabricante/etc ali, só por região); os demais filtros (Segmento,
  Fabricante, Marca, Submarca, Variante, Sub Variante) ficam livres,
  tratados como na quebra "Segmento" (cadeia inteira disponível como
  recorte antes de quebrar por região — ver `_selection_start_cod`).
  IsBodySplash segue a mesma regra do resto do app: só habilita quando
  Submarca/Variante/Sub Variante está fixo (única granularidade onde a
  classificação existe), e nesse caso Segmento também é forçado pra um
  valor real (não "Total"), mesma restrição de
  `SEGMENT_REQUIRED_BREAKDOWNS`. Vale pra Price/Unit e Adições também
  (que passam a quebrar por região do mesmo jeito). Dropdown "Quebra
  por" (Segmento / Fabricante / Marca / Submarca / Variante / Sub
  Variante / Body Splash / Embalagem Tipo / Embalagem Conteúdo) e
  filtros em cascata (Segmento independente; Fabricante → Marca →
  Submarca/Variante/Sub Variante) fixos pras dimensões que não estão
  sendo usadas como quebra, mais um filtro à parte, IsBodySplash
  (Sim/Não/Total). Marca/Submarca/Variante/Sub Variante com muitas
  categorias usam um seletor de top N (10/20/30), sem grupo sintético
  "Outros" (o top N é só um recorte, não fecha 100% — daí o
  `coverage_pct` no gráfico). Fabricante tem seletor próprio (Top
  5/6/10, padrão 6) e um checkbox "Incluir bloco 'Demais Fabricantes'":
  marcado (padrão), soma um bloco sintético com o resto do ranking e
  fecha o total real; desmarcado, mostra só o top N filtrado e cai no
  mesmo `coverage_pct` usado por Marca/Submarca/Variante.
  - **Fabricante ≠ Marca de mesmo nome** — um Fabricante costuma ser um
    grupo corporativo dono de várias Marcas, nem sempre só a de nome
    igual ao dele. Ex.: Fabricante "Boticário" soma 3 Marcas (Boticário,
    Eudora, Quem Disse Berenice) — o total de Fabricante=Boticário é
    maior que o de Marca=Boticário sozinha (a diferença é exatamente
    Eudora + Quem Disse Berenice). Confirmado com o usuário: não é bug,
    a soma das Marcas do Fabricante bate exatamente com o total dele.
  - **Body Splash** (quebra) — 2 categorias fixas, "Body Splash" e "Não
    Body Splash", que sempre somam 100% do indicador no filtro atual
    (sem ranking/top N, já que só há 2 categorias) — compara o
    crescimento da linha Body Splash contra o resto do mercado/marca.
    Combina com toda a cadeia Região/Segmento/Fabricante/Marca/Submarca/
    Variante/Sub Variante (qualquer filtro fixo restringe o escopo
    antes do split); Segmento é forçado pra um valor real (não "Total"),
    mesma restrição de Marca/Submarca/Variante/Sub Variante, já que a
    classificação IsBodySplash só existe dentro de um segmento
    específico na planilha. O filtro IsBodySplash avulso fica travado
    (resetado pra "Total") enquanto essa quebra está ativa. Implementada
    descendo a árvore de `Cód.` até as folhas de verdade (SKUs), sem
    parar num nível-alvo como as demais quebras (ver
    `_body_splash_values`/`_body_splash_leaves` em `app.py`).
  - **IsBodySplash** (filtro) — só fica habilitado combinado com quebra
    por Submarca/Variante/Sub Variante (`BODY_SPLASH_BREAKDOWNS`): é
    nessas 3 quebras que a classificação Sim/Não (de
    `fonte/body_splash.xlsx`, juntada por `Cód.`) é confiável — nenhum
    Fabricante/Marca inteiro é 100% Body Splash, então filtrar por esses
    níveis daria números vazios/errados.
  Abas de indicador: Volume / Unidades / Valor com Presentes /
  Compradores / Penetração / Vol. por Comprador / Frequência / Preço
  Médio (Litros) (gráfico + tabela de variação + legenda + Highlights,
  um bloco por indicador) mais três abas à parte:
  - **Price/Unit** — um waterfall por categoria decompondo a variação
    do Valor com Presentes em efeito Unidades × efeito Preço Médio;
    waterfall totalizador (soma de todas as categorias) no topo quando
    a quebra é Segmento ou Fabricante.
  - **Adições de Unidades** / **Adições de Valor com Presente** — duas
    abas idênticas (mesmo layout/lógica, só troca o indicador, ver
    `ADDITIONS_TABS`): um waterfall/"bridge" com a decomposição por
    categoria da diferença do indicador entre o penúltimo e o último ano
    (hoje 2024→2025 — só essa transição, não o período inteiro), maior
    adição primeiro na tabela ao lado; reusam o mesmo seletor de top N
    da quebra ativa (Marca/Submarca/Variante/Sub Variante) em vez de ter
    um próprio — a quebra Body Splash, sem ranking, tampouco precisa
    dele.

- **`export_pptx.py`** — exporta qualquer bloco (gráfico + tabela) ou a
  aba Price/Unit pra PowerPoint, com os MESMOS números da tela
  (reaproveita `compute_variations`/os `dict`s de valores já
  calculados). Logo Symrise + "Kantar Worldpanel - Dashboard" no canto superior
  esquerdo e rodapé com a fonte dos dados em todo slide; fonte Roboto
  Condensed; tabela com "scale to fit" (encolhe fonte/margem pra caber
  num único slide, com piso legível — o que não couber nem assim
  transborda pra slide de continuação).
  `new_presentation()`/`add_chart_slides()` são a versão reusável desse
  mesmo layout: em vez de um deck por gráfico (o que os botões da tela
  baixam, via `build_pptx`), deixam empilhar vários blocos num deck só —
  é o que `sequencia.py` usa. Toda caixa de Highlights sai com o nome
  fixo `symrise-highlight`, que é o que permite reescrever só os textos
  depois (ver `highlights.py`).

- **`sequencia.py`** — monta UM deck com uma sequência de recortes do
  dashboard, na ordem de uma narrativa de análise (ex.: peso das regiões
  no Valor com Presente → dentro de N+NE, Body Splash vs. resto → marcas
  → submarcas), em vez de baixar um `.pptx` por bloco pela tela e juntar
  na mão. A sequência é a lista `STEPS` no topo do arquivo — cada passo é
  a mesma combinação de filtros que você montaria clicando. Chama
  `app._build_blocks`, exatamente o que a tela chama, então os números
  batem por construção. **Valida cada passo antes de gerar**: a UI impede
  combinações inválidas (quebra por Marca/Submarca/Variante/Sub Variante/
  Body Splash exige Segmento real, o filtro IsBodySplash só vale em certas
  quebras etc.), e um script passaria por cima dessas travas produzindo
  número errado com cara de certo — daí ele recusar o passo com a razão
  em vez de gerar. Imprime um manifesto slide→passo no fim.
  Rodar: `uv run python sequencia.py -o analise.pptx`.

- **`highlights.py`** — lê e reescreve SÓ os textos de Highlights de um
  `.pptx` já gerado; gráficos, tabelas, logo e rodapé ficam intactos.
  Pensado pro ciclo da análise: gera o deck com os highlights automáticos,
  abre no PowerPoint, decide o que cada slide deveria dizer, aplica os
  textos novos sem regerar nada. Sem argumentos, imprime o que há hoje
  em cada slide; com `-a textos.txt`, aplica (formato: um `## <nº do
  slide>` por bloco, só os slides que mudam; linha em branco separa
  parágrafos). Preserva a formatação atribuindo `run.text` — atribuir
  `text_frame.text` colapsaria o parágrafo num run sem estilo, perdendo
  fonte/corpo/cor. Funciona também nos decks baixados pelos botões da
  tela. Rodar: `uv run python highlights.py analise.pptx -a textos.txt`.

- **`translations.py`** — dashboard é em inglês (migrado de português em
  2026-09); `translate(texto)` é um dicionário PT→EN aplicado em tempo
  de exibição a qualquer rótulo/categoria que vem da planilha (valores
  de Segmento, nomes de região, buckets sintéticos de ranking como
  "Other"/"Other Manufacturers"). Nomes próprios de Fabricante/Marca/
  Sub Marca/Variante/Sub Variante (ex.: "Boticário", "Floratta") NUNCA
  entram nesse dicionário — `translate()` devolve sem alteração
  qualquer termo que não esteja cadastrado, então nomes próprios passam
  intactos automaticamente, sem precisar de lista de exceção. Textos
  fixos de interface (labels, botões, cabeçalhos, frases dos
  Highlights, tela de login, export PowerPoint) estão hardcoded em
  inglês direto no código de cada módulo, não passam por esse
  dicionário. Pra ajustar alguma tradução, editar `TRANSLATIONS` aqui —
  a mudança reflete em todo o app (dropdowns, gráficos, tabelas,
  breadcrumbs, PPTX) sem mexer em outro arquivo.

## Fluxo de análise (deck em sequência)

Pra montar uma análise narrativa — uma sequência de recortes que conta
uma história, em vez de um gráfico solto — o ciclo é:

1. **Descrever a sequência** em `STEPS`, no topo de `sequencia.py`. Cada
   passo é a mesma combinação de filtros que você montaria clicando no
   dashboard (região, quebra, segmento, top N, ...).
2. **Gerar**: `uv run python sequencia.py -o analise.pptx`. Sai um deck
   só, na ordem dos passos, com os highlights automáticos de sempre e um
   manifesto slide→passo impresso no fim.
3. **Reescrever os textos**: abrir no PowerPoint, decidir o que cada
   slide deveria dizer, e aplicar com
   `uv run python highlights.py analise.pptx -a textos.txt`. Só as caixas
   de Highlights mudam — gráficos, tabelas, logo e rodapé ficam intactos,
   então não é preciso regerar nada.

Atualizou a planilha? Rodar o passo 2 de novo reconstrói o deck inteiro
com os números novos, sem refazer cliques. Os textos do passo 3 precisam
ser reaplicados (ou revistos, já que os números mudaram).

### Restrição que mais atrapalha narrativa

**Quebra por Marca, Submarca, Variante, Sub Variante ou Body Splash
exige um Segmento real** (Feminino / Masculino / Infantil / Unisex) —
não funciona sobre `Segmento="Total"`. Não é limitação da interface: a
planilha não detalha esses níveis na linha agregada (Submarca/Variante/
Sub Variante não têm nenhuma linha em "Total"; Marca tem algumas, mas
misturadas com totais de fabricante reaproveitados pela descida
genérica, o que é pior que não ter).

Na prática, uma narrativa do tipo "peso da região → dentro dela, Body
Splash → marcas → submarcas" **não fecha em cima do total da região**.
As opções são escolher um segmento como fio condutor, ou repetir o
bloco por segmento. `sequencia.py` recusa o passo inválido explicando o
motivo, em vez de gerar um número errado com cara de certo.

## Deploy / Produção

Em produção em `https://gettally.com.br/symrise/dashboard/` (VPS
Ubuntu), atrás de login próprio (não é o pop-up nativo do navegador).

- **Subpath** — `app.py` lê `DASH_URL_BASE_PATHNAME` (default `"/"`,
  sem efeito no uso local) pra configurar o `url_base_pathname` do
  Dash; em produção fica `/symrise/dashboard/`, casando com o
  `location` do nginx que faz o proxy reverso.
- **WSGI** — `server = app.server` (fim de `app.py`) é o entrypoint pro
  gunicorn (`gunicorn app:server`); local continua rodando
  `python app.py` (dev server do Dash) normalmente.
- **Login** (`auth.py`) — sessão Flask (cookie assinado, 7 dias,
  renovada a cada acesso, `Secure` só em produção), com tela de login
  própria (mesma identidade visual do resto do app) em vez do HTTP
  Basic Auth do navegador. Protege tudo sob `DASH_URL_BASE_PATHNAME`
  via `before_request`, liberando só `/login` e os assets estáticos
  (necessários pra a própria tela de login renderizar). Botão "Sair"
  no cabeçalho chama `/logout`. Usuário/senha via
  `DASH_AUTH_USERNAME`/`DASH_AUTH_PASSWORD` (env vars no servidor);
  `SECRET_KEY` também via env var, pra sessões sobreviverem a um
  restart do serviço.
- **Servidor** — `systemd` (`symrise.service`) roda
  `uv run gunicorn -b 127.0.0.1:8060 app:server`, reinicia sozinho se
  cair; `nginx` faz o proxy reverso + TLS (Let's Encrypt via certbot,
  renovação automática).
- **Deploy automático** — todo push na `main` dispara
  `.github/workflows/deploy.yml`: conecta no VPS via SSH (secrets
  `VPS_HOST`/`VPS_DEPLOY_KEY`, cadastrados como *repository secrets* no
  GitHub) e roda `/opt/symrise/deploy.sh` (`git pull` + `uv sync` +
  `systemctl restart symrise`). A chave de deploy é restrita por
  `command=` no `authorized_keys` do servidor — mesmo que vaze, só
  consegue rodar esse script, nada mais.
- **Exportação PowerPoint em produção** — depende do Kaleido conseguir
  abrir um Chrome headless pra renderizar os gráficos em PNG. O
  servidor precisa ter, além do Chrome do próprio Kaleido
  (`uv run plotly_get_chrome`), as bibliotecas de sistema que ele
  carrega em runtime (`libatk-1.0`, `libnss3`, `libgtk-3`, etc. —
  pacotes padrão de Chrome headless no Ubuntu). Isso é infraestrutura
  do servidor, não fica registrado no repo — se o VPS for recriado do
  zero, esse passo precisa ser refeito manualmente.
- **Credenciais do servidor** — acesso ao VPS é só por chave SSH
  (sem senha); a senha de root original (usada uma única vez pra
  instalar a chave) não é mais necessária no dia a dia.

## Status atual

**Feito:**
- ETL validado (5.742 linhas, 56 colunas, incluindo `is_body_splash`)
- Os 12 indicadores do escopo cobertos pelos templates de gráfico, mais
  a decomposição Unidades×Preço (Price/Unit) e as adições de Unidades/
  Valor com Presentes na transição 2024→2025
- Comentário automático (highlights) por categoria/waterfall
- Filtros combináveis de Região/Segmento/Fabricante/Marca/Submarca/
  Variante/Sub Variante/IsBodySplash, com quebra dinâmica; duas quebras
  à parte de Embalagem (Tipo/Conteúdo), descobertas na planilha e não
  documentadas no ESCOPO.md — só combinam com Região; mais uma quebra à
  parte, Body Splash (Body Splash vs. Não Body Splash, 2 categorias que
  fecham 100% do total, sem ranking)
- Exportação PowerPoint (não PDF) com identidade visual Symrise, fiel
  aos números da tela — inclusive nas abas Adições de Unidades/Valor
  com Presentes
- Deploy em produção (VPS + nginx + systemd + TLS), com login próprio
  e deploy automático via GitHub Actions a cada push na `main`
- Paleta de cores oficial de Fabricante/Marca/Sub Marca/Variante/Sub
  Variante/Embalagem/Segmento, lida direto de `fonte/hexa_colors.xlsx`;
  contraste de texto (sobre barra ou como linha/rótulo) calculado
  automaticamente pra qualquer cor da paleta, sem depender de uma
  coluna extra cadastrada cor a cor
- Geração de deck em sequência (`sequencia.py`) + reescrita só dos
  textos de Highlights num deck pronto (`highlights.py`) — ver "Fluxo de
  análise" acima
- Dashboard traduzido de português para inglês (ver `translations.py`)
  — nomes próprios de Fabricante/Marca/Sub Marca/Variante/Sub Variante
  continuam como vêm da planilha, todo o resto (interface, categorias
  de gráfico/tabela, highlights, export PowerPoint, login) em inglês

**Em aberto:**
- Share Unidades / Share Valor com Presentes só funcionam quebrados por
  Segmento — a relação pai/filho do `Cód.` para esses dois indicadores
  ainda não foi resolvida para quebra por Fabricante/Marca
- Exportação em múltiplas folhas A4 (PDF) — hoje só PowerPoint
  (ESCOPO.md seção 5)
