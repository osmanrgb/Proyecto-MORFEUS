"""Detección de trends actuales.

Estrategia (en orden de fiabilidad):
  1. Google Trends — vía pytrends. Robusto y oficialmente público.
  2. TikTok Creative Center — endpoint público no oficial, frágil pero rico.

Cualquier fuente que falle se ignora silenciosamente; siempre devolvemos
al menos los resultados de las que sí funcionaron. Si todas fallan, la lista
queda vacía y el caller cae al `trend` por defecto.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from typing import Iterable

import httpx

log = logging.getLogger("morfeus.trends.scout")


@dataclass
class TrendCandidate:
    name: str
    description: str = ""
    score: float = 1.0  # 0..N (más alto = más viral)
    source: str = "unknown"
    region: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TrendCandidate":
        return cls(**d)


# ---------------------------------------------------------------------------
# Google Trends (pytrends)
# ---------------------------------------------------------------------------

_PYTRENDS_REGIONS = {
    "MX": "mexico",
    "ES": "spain",
    "AR": "argentina",
    "CO": "colombia",
    "CL": "chile",
    "PE": "peru",
    "US": "united_states",
}


def _scout_google_trends(region: str, limit: int) -> list[TrendCandidate]:
    try:
        from pytrends.request import TrendReq  # type: ignore[import-untyped]
    except ImportError:
        log.info("pytrends no instalado; salto Google Trends.")
        return []

    pn = _PYTRENDS_REGIONS.get(region.upper())
    if not pn:
        log.info("Google Trends no soporta región %s; salto.", region)
        return []

    try:
        py = TrendReq(hl="es-MX", tz=360)
        df = py.trending_searches(pn=pn)
        items = df.iloc[:, 0].tolist()
    except Exception as exc:
        log.warning("Google Trends falló: %s", exc)
        return []

    out: list[TrendCandidate] = []
    for i, name in enumerate(items[:limit]):
        out.append(
            TrendCandidate(
                name=str(name),
                description=f"Google Trends (top {i + 1})",
                score=float(limit - i),
                source="google_trends",
                region=region.upper(),
            )
        )
    return out


# ---------------------------------------------------------------------------
# TikTok Creative Center (frágil — endpoint público no oficial)
# ---------------------------------------------------------------------------

_TT_CC_HASHTAG_URL = (
    "https://ads.tiktok.com/creative_radar_api/v1/popular_trend/hashtag/list"
)
_TT_REGIONS = {"MX", "ES", "AR", "CO", "CL", "PE", "US"}


def _scout_tiktok_cc(region: str, limit: int) -> list[TrendCandidate]:
    region = region.upper()
    if region not in _TT_REGIONS:
        return []
    params = {
        "page": 1,
        "limit": min(limit, 30),
        "period": 7,
        "country_code": region,
        "sort_by": "popular",
    }
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Referer": "https://ads.tiktok.com/business/creativecenter/inspiration/popular/hashtag/pc/en",
    }
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            r = client.get(_TT_CC_HASHTAG_URL, params=params, headers=headers)
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        log.info("TikTok Creative Center falló (%s); ignorando.", exc)
        return []

    items = (data.get("data") or {}).get("list") or []
    out: list[TrendCandidate] = []
    for i, it in enumerate(items[:limit]):
        name = it.get("hashtag_name") or it.get("name")
        if not name:
            continue
        out.append(
            TrendCandidate(
                name=f"#{name}" if not str(name).startswith("#") else str(name),
                description=f"TikTok #{name}, posts: {it.get('publish_cnt') or '?'}",
                score=float(limit - i) * 1.2,  # ligeramente preferida (es TikTok directamente)
                source="tiktok_cc",
                region=region,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Orquestador
# ---------------------------------------------------------------------------

def discover_trends(region: str = "MX", limit: int = 12) -> list[TrendCandidate]:
    """Devuelve trends combinados de todas las fuentes disponibles, deduplicados."""
    pool: list[TrendCandidate] = []
    for fetcher in (_scout_tiktok_cc, _scout_google_trends):
        try:
            pool.extend(fetcher(region, limit))
        except Exception as exc:  # blindaje extra
            log.warning("Fuente %s falló: %s", fetcher.__name__, exc)

    return _dedupe_and_sort(pool)[:limit]


def _normalize(name: str) -> str:
    return re.sub(r"[\s#@_-]+", "", name.lower())


def _dedupe_and_sort(items: Iterable[TrendCandidate]) -> list[TrendCandidate]:
    seen: dict[str, TrendCandidate] = {}
    for it in items:
        key = _normalize(it.name)
        if not key:
            continue
        if key not in seen or it.score > seen[key].score:
            seen[key] = it
    return sorted(seen.values(), key=lambda t: t.score, reverse=True)
