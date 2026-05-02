"""Caché simple de trends en disco (24h)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from morfeus.trends.scout import TrendCandidate, discover_trends

DEFAULT_TTL_SECONDS = 24 * 60 * 60


def _cache_dir() -> Path:
    base = os.environ.get("MORFEUS_CACHE_DIR")
    if base:
        return Path(base).expanduser().resolve()
    return Path.home() / ".morfeus_cache" / "trends"


def _cache_file(region: str) -> Path:
    return _cache_dir() / f"trends_{region.upper()}.json"


def get_or_fetch_trends(
    region: str = "MX",
    limit: int = 12,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    force_refresh: bool = False,
) -> list[TrendCandidate]:
    f = _cache_file(region)
    f.parent.mkdir(parents=True, exist_ok=True)

    if not force_refresh and f.exists():
        age = time.time() - f.stat().st_mtime
        if age < ttl_seconds:
            try:
                payload = json.loads(f.read_text(encoding="utf-8"))
                return [TrendCandidate.from_dict(d) for d in payload][:limit]
            except (json.JSONDecodeError, TypeError, ValueError):
                pass  # caché corrupta — re-fetch

    trends = discover_trends(region=region, limit=limit)
    if trends:
        try:
            f.write_text(
                json.dumps([t.to_dict() for t in trends], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass  # FS read-only o lo que sea — no es fatal
    return trends
