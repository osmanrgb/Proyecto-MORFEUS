"""Matcher: dado un producto, elige el trend más relevante de la lista."""

from __future__ import annotations

import re

from morfeus.trends.scout import TrendCandidate


_STOPWORDS_ES = {
    "el", "la", "los", "las", "un", "una", "unos", "unas",
    "de", "del", "al", "y", "o", "u", "para", "por", "con",
    "en", "a", "es", "ser", "que", "mi", "tu", "su", "nuestro",
}


def _tokens(text: str) -> set[str]:
    text = text.lower()
    text = re.sub(r"[^\w\s#áéíóúñü]", " ", text, flags=re.UNICODE)
    return {t for t in text.split() if t and t not in _STOPWORDS_ES and len(t) > 2}


def relevance(producto: str, trend: TrendCandidate) -> float:
    """Heurística simple: solapamiento léxico + bonus por fuente y score."""
    p_tokens = _tokens(producto)
    t_tokens = _tokens(f"{trend.name} {trend.description}")
    if not p_tokens or not t_tokens:
        overlap = 0.0
    else:
        common = p_tokens & t_tokens
        overlap = len(common) / max(1, len(p_tokens))

    source_bonus = {"tiktok_cc": 1.5, "google_trends": 1.0}.get(trend.source, 0.8)
    # score viene de scout, normalizado a algo razonable.
    popularity = min(trend.score, 30) / 30.0

    return overlap * 3.0 + popularity + source_bonus * 0.5


def pick_trend(producto: str, trends: list[TrendCandidate]) -> TrendCandidate | None:
    if not trends:
        return None
    ranked = sorted(trends, key=lambda t: relevance(producto, t), reverse=True)
    return ranked[0]


def trend_to_prompt_phrase(trend: TrendCandidate | None) -> str:
    """Convierte un TrendCandidate en una frase para inyectar en el prompt del LLM."""
    if trend is None:
        return "humor seco, ritmo rápido, gancho final viral"
    return (
        f"aprovecha el trend '{trend.name}' ({trend.description}); "
        f"haz que el guion suene fresco y con la energía de ese trend"
    )
