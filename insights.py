"""Gerador de comentario dinamico para acompanhar um grafico: descreve a
trajetoria de cada categoria (crescimento/recuo, comparado ao mercado
total) e o ganho/perda de participacao (MS) no periodo, alem de
aproximar categorias de participacao parecida que estao divergindo.

E texto puro derivado dos mesmos dados do grafico (sem IA generativa) -
por isso, num dashboard interativo, o mesmo callback que redesenha o
grafico ao trocar um filtro recalcula este texto junto.

Uso tipico:

    from etl import build_dataset
    from insights import generate_insight

    df = build_dataset()
    texto = generate_insight(
        df,
        indicator="unidades",
        dimension="regiao",
        categories=["N+NE", "Sudeste", "C.Oeste", "Sul"],
        filters={...},
        value_scale=1 / 1_000_000,
        unit_label="milhoes",
    )
"""

from __future__ import annotations

from charts import YEARS_DEFAULT, compute_values, pct_change, price_unit_effects

MAX_CHARS = 500

# abaixo disso uma variacao (%) e tratada como estabilidade, nao como
# crescimento/recuo
_FLAT_PCT = 0.5

# diferenca minima (pontos percentuais) entre a categoria e o mercado
# para valer comentar a comparacao
_MARKET_DIFF_MIN_PP = 2.0

# mudanca minima de participacao (pp) para valer comentar ganho/perda de MS
_SHARE_CHANGE_MIN_PP = 0.5

# duas categorias sao tratadas como "vizinhas" em participacao se a
# diferenca de share for menor que isso (pp)
_PEER_SHARE_MAX_DIFF_PP = 6.0


def _year_label(yr: str) -> str:
    return yr.replace("Y", "")


def _trend_phrase(cat: str, last: float | None, prev: float | None) -> str:
    if last is None:
        return f"{cat} sem variação calculável"
    if last > _FLAT_PCT:
        if prev is not None and prev > _FLAT_PCT:
            return f"{cat} continua trajetória de crescimento, com alta de {last:+.1f}%"
        return f"{cat} cresce {last:+.1f}%"
    if last < -_FLAT_PCT:
        if prev is not None and prev < -_FLAT_PCT:
            return f"{cat} segue em queda, recuando {last:+.1f}%"
        return f"{cat} recuou {last:+.1f}%"
    return f"{cat} ficou estável ({last:+.1f}%)"


def _market_phrase(last: float | None, market: float | None, is_largest: bool) -> str:
    if last is None or market is None:
        return ""
    diff = last - market
    if abs(diff) < _MARKET_DIFF_MIN_PP:
        return ""
    same_sign = (last >= 0) == (market >= 0)
    if same_sign:
        direcao = "crescimento" if market >= 0 else "recuo"
        # "acima do recuo" = recuo maior (mais negativo); "acima do
        # crescimento" = crescimento maior (mais positivo) - por isso o
        # sentido da comparacao inverte quando o mercado esta em recuo
        maior_magnitude = last < market if market < 0 else last > market
        rel = "acima" if maior_magnitude else "abaixo"
        phrase = f"{rel} do {direcao} do mercado ({market:+.1f}%)"
        if is_largest and rel == "acima":
            phrase += ", puxando a média do mercado"
        return phrase
    return f"na contramão do mercado ({market:+.1f}%)"


def _share_phrase(share_change_pp: float | None) -> str:
    if share_change_pp is None or abs(share_change_pp) < _SHARE_CHANGE_MIN_PP:
        return ""
    verbo = "ganhando" if share_change_pp > 0 else "perdendo"
    return f"{verbo} {abs(share_change_pp):.1f}pp em MS"


def generate_insight(
    df,
    indicator: str,
    dimension: str,
    categories: list[str],
    years: tuple[str, ...] = YEARS_DEFAULT,
    filters: dict[str, str] | None = None,
    value_scale: float = 1.0,
    value_decimals: int = 1,
    unit_label: str = "",
    additive: bool = True,
    max_chars: int = MAX_CHARS,
    values_override: dict[str, dict[str, float]] | None = None,
    totals_override: dict[str, float] | None = None,
) -> str:
    """Monta um comentario descrevendo a trajetoria de cada categoria no
    ultimo ano do periodo: crescimento/recuo (comparado ao mercado total,
    quando `additive=True`), ganho/perda de participacao (MS) e uma
    aproximacao entre categorias de participacao parecida que estao
    divergindo. `categories` deve vir ordenada da maior para a menor
    (mesma convencao usada nos graficos). `values_override`: ver
    docstring de `charts.alluvial_stack_chart`. `totals_override`: ver
    `charts.compute_variations` - usa esse total (em vez da soma de
    `categories`) pra participacao (MS) e pra variacao "do mercado",
    quando `categories` e so um recorte top N.
    """
    if len(years) < 2:
        return ""

    values = values_override or compute_values(df, indicator, dimension, categories, years, filters, value_scale)

    changes: dict[str, list[float | None]] = {
        cat: [
            pct_change(values[cat][years[i]], values[cat][years[i + 1]])
            for i in range(len(years) - 1)
        ]
        for cat in categories
    }

    last_year = _year_label(years[-1])
    last_pct = {cat: changes[cat][-1] for cat in categories}
    prev_pct = {cat: (changes[cat][-2] if len(years) >= 3 else None) for cat in categories}

    if totals_override is not None:
        totals_last = totals_override[years[-1]] if additive else None
        totals_prev = totals_override[years[-2]] if additive else None
    else:
        totals_last = sum(values[cat][years[-1]] for cat in categories) if additive else None
        totals_prev = sum(values[cat][years[-2]] for cat in categories) if additive else None
    market_pct = pct_change(totals_prev, totals_last) if additive else None

    share_last = {
        cat: (values[cat][years[-1]] / totals_last * 100 if additive and totals_last else None)
        for cat in categories
    }
    share_prev = {
        cat: (values[cat][years[-2]] / totals_prev * 100 if additive and totals_prev else None)
        for cat in categories
    }
    share_change = {
        cat: (
            share_last[cat] - share_prev[cat]
            if share_last[cat] is not None and share_prev[cat] is not None
            else None
        )
        for cat in categories
    }

    largest_cat = categories[0] if categories else None

    # aproxima categorias "vizinhas" em participacao que estao divergindo
    # (uma sobe, outra cai) - comentada apenas na de menor participacao
    peer_note: dict[str, str] = {}
    if additive:
        used_as_peer: set[str] = set()
        for a in categories:
            if a in used_as_peer or share_last.get(a) is None or last_pct.get(a) is None:
                continue
            for b in categories:
                if b == a or b in used_as_peer or share_last.get(b) is None or last_pct.get(b) is None:
                    continue
                same_direction = (last_pct[a] >= 0) == (last_pct[b] >= 0)
                close_share = abs(share_last[a] - share_last[b]) <= _PEER_SHARE_MAX_DIFF_PP
                if close_share and not same_direction:
                    smaller, other = (a, b) if share_last[a] <= share_last[b] else (b, a)
                    if smaller in peer_note:
                        continue
                    verbo = "cresceu" if last_pct[other] > 0 else "caiu"
                    peer_note[smaller] = (
                        f"muito próximo da participação de {other}, que {verbo} {last_pct[other]:+.1f}%"
                    )
                    used_as_peer.add(a)
                    used_as_peer.add(b)
                    break

    sentences: list[str] = []
    for cat in categories:
        fragments = [_trend_phrase(cat, last_pct.get(cat), prev_pct.get(cat))]
        # a comparacao com o mercado so aparece na categoria de maior peso
        # (e ela quem mais explica o resultado do total) - repetir "na
        # contramao do mercado" em toda categoria vira ruido
        if cat == largest_cat:
            market_frag = _market_phrase(last_pct.get(cat), market_pct, True)
            if market_frag:
                fragments.append(market_frag)
        share_frag = _share_phrase(share_change.get(cat))
        if share_frag:
            fragments.append(share_frag)
        if cat in peer_note:
            porem = "porém ainda " if (share_last.get(cat) or 0) < 15 else ""
            share_txt = f"{porem}{share_last[cat]:.1f}% do total" if share_last.get(cat) is not None else ""
            extra = ", ".join(x for x in (share_txt, peer_note[cat]) if x)
            fragments.append(extra)
        sentences.append(", ".join(fragments))

    if not sentences:
        return f"Sem variação relevante em {last_year} no período analisado."

    text = ""
    for sentence in sentences:
        addition = (" " if text else "") + sentence[0].upper() + sentence[1:] + "."
        if len(text + addition) > max_chars:
            break
        text += addition
    return text


def generate_price_unit_insight(
    unidades: dict[str, float], valor: dict[str, float], years: tuple[str, ...] = YEARS_DEFAULT,
) -> str:
    """Comentario pro waterfall de `charts.price_unit_waterfall_chart`:
    de quanto do crescimento/queda do Valor com Presentes na ULTIMA
    transicao de ano (ex.: 2024->2025) e responsabilidade de cada efeito
    (Unidades vendidas vs Preco Medio) - ver `charts.price_unit_effects`
    pra formula. Cobre as 4 combinacoes de sinal possiveis (unidades e
    preco na mesma direcao, ou em direcoes opostas)."""
    effects = price_unit_effects(unidades, valor, years)
    if not effects:
        return ""
    last = effects[-1]
    total_pct, unit_pct, price_pct = last["total_pct"], last["unit_pct"], last["price_pct"]
    if total_pct is None or unit_pct is None or price_pct is None:
        return "Sem variação calculável no último período."

    yr_label = last["yr1"].replace("Y", "")
    prev_label = last["yr0"].replace("Y", "")
    units_up = unit_pct >= 0
    price_up = price_pct >= 0

    dominant_is_price = abs(price_pct) >= abs(unit_pct)
    dominant_pct = price_pct if dominant_is_price else unit_pct
    dominant_label = "preço" if dominant_is_price else "unidades vendidas"
    causal = (
        "ações de reprecificação, mudança de mix, política de descontos, entre outras decisões"
        if dominant_is_price
        else "ganho ou perda de penetração/distribuição, sazonalidade, ações promocionais de volume, entre outros fatores"
    )
    growth_phrase = (
        f"do crescimento de {total_pct:.1f}%" if total_pct >= 0 else f"da queda de {abs(total_pct):.1f}%"
    )

    if units_up == price_up:
        verbo = "cresceram" if units_up else "caíram"
        text = (
            f"Tanto as vendas de unidades quanto o preço médio {verbo} em {yr_label} (ante {prev_label}), "
            f"sendo {abs(dominant_pct):.1f}% {growth_phrase} no Valor com Presentes de responsabilidade "
            f"do efeito {dominant_label}, que pode ser derivado de {causal}."
        )
    else:
        unidades_verbo = "cresceram" if units_up else "caíram"
        preco_verbo = "cresceu" if price_up else "caiu"
        text = (
            f"As vendas de unidades {unidades_verbo} ({unit_pct:+.1f}%) enquanto o preço médio {preco_verbo} "
            f"({price_pct:+.1f}%) em {yr_label} (ante {prev_label}); o efeito {dominant_label} foi "
            f"determinante, respondendo por {abs(dominant_pct):.1f}% {growth_phrase} no Valor com "
            f"Presentes, que pode ser derivado de {causal}."
        )
    return text
