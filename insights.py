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

from charts import YEARS_DEFAULT, compute_values

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


def _pct_change(prev: float, curr: float) -> float | None:
    if prev == 0:
        return None
    return (curr - prev) / prev * 100


def _year_label(yr: str) -> str:
    return yr.replace("Y", "")


def _trend_phrase(cat: str, last: float | None, prev: float | None) -> str:
    if last is None:
        return f"{cat} sem variacao calculavel"
    if last > _FLAT_PCT:
        if prev is not None and prev > _FLAT_PCT:
            return f"{cat} continua trajetoria de crescimento, com alta de {last:+.0f}%"
        return f"{cat} cresce {last:+.0f}%"
    if last < -_FLAT_PCT:
        if prev is not None and prev < -_FLAT_PCT:
            return f"{cat} segue em queda, recuando {last:+.0f}%"
        return f"{cat} recuou {last:+.0f}%"
    return f"{cat} ficou estavel ({last:+.0f}%)"


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
        phrase = f"{rel} do {direcao} do mercado ({market:+.0f}%)"
        if is_largest and rel == "acima":
            phrase += ", puxando a media do mercado"
        return phrase
    return f"na contramao do mercado ({market:+.0f}%)"


def _share_phrase(share_change_pp: float | None) -> str:
    if share_change_pp is None or abs(share_change_pp) < _SHARE_CHANGE_MIN_PP:
        return ""
    verbo = "ganhando" if share_change_pp > 0 else "perdendo"
    return f"{verbo} {abs(share_change_pp):.0f}pp em MS"


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
) -> str:
    """Monta um comentario descrevendo a trajetoria de cada categoria no
    ultimo ano do periodo: crescimento/recuo (comparado ao mercado total,
    quando `additive=True`), ganho/perda de participacao (MS) e uma
    aproximacao entre categorias de participacao parecida que estao
    divergindo. `categories` deve vir ordenada da maior para a menor
    (mesma convencao usada nos graficos). `values_override`: ver
    docstring de `charts.alluvial_stack_chart`.
    """
    if len(years) < 2:
        return ""

    values = values_override or compute_values(df, indicator, dimension, categories, years, filters, value_scale)

    changes: dict[str, list[float | None]] = {
        cat: [
            _pct_change(values[cat][years[i]], values[cat][years[i + 1]])
            for i in range(len(years) - 1)
        ]
        for cat in categories
    }

    last_year = _year_label(years[-1])
    last_pct = {cat: changes[cat][-1] for cat in categories}
    prev_pct = {cat: (changes[cat][-2] if len(years) >= 3 else None) for cat in categories}

    totals_last = sum(values[cat][years[-1]] for cat in categories) if additive else None
    totals_prev = sum(values[cat][years[-2]] for cat in categories) if additive else None
    market_pct = _pct_change(totals_prev, totals_last) if additive else None

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
                        f"muito proximo da participacao de {other}, que {verbo} {last_pct[other]:+.0f}%"
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
            porem = "porem ainda " if (share_last.get(cat) or 0) < 15 else ""
            share_txt = f"{porem}{share_last[cat]:.0f}% do total" if share_last.get(cat) is not None else ""
            extra = ", ".join(x for x in (share_txt, peer_note[cat]) if x)
            fragments.append(extra)
        sentences.append(", ".join(fragments))

    if not sentences:
        return f"Sem variacao relevante em {last_year} no periodo analisado."

    text = ""
    for sentence in sentences:
        addition = (" " if text else "") + sentence[0].upper() + sentence[1:] + "."
        if len(text + addition) > max_chars:
            break
        text += addition
    return text
