"""
Daily 'up and coming' rotation.

We score every ticker in the universe with a composite of:
  - 5/20/60-day momentum (Jegadeesh & Titman 1993, JF — momentum factor)
  - Volume surge vs. trailing average (institutional accumulation proxy)
  - Drawdown-from-high (avoids picks that already blew off the top)

A new pseudo-random rotation seed is mixed in each calendar day so the
panel feels fresh, but the underlying ranking is deterministic for that day.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import List

from data_fetcher import screen_universe_quick


def _daily_seed() -> int:
    h = hashlib.sha256(dt.date.today().isoformat().encode()).hexdigest()
    return int(h[:8], 16)


def daily_rotation(top_n: int = 6) -> List[dict]:
    rows = screen_universe_quick()
    if not rows:
        return []

    # Composite score. Each piece is z-ish normalized by clipping.
    def clamp(x, lo=-1, hi=1):
        return max(lo, min(hi, x))

    scored = []
    for r in rows:
        momentum = (
            0.5 * clamp(r["ret_5"] * 5)
            + 0.3 * clamp(r["ret_20"] * 2.5)
            + 0.2 * clamp(r["ret_60"])
        )
        volume = clamp((r["vol_ratio"] - 1.0), -1, 2)
        # Penalize names that already blew well above prior highs
        drawdown_bonus = 0.5 * clamp(r["pct_off_high"] * 4)  # negative when near highs
        # Reward names within ~10% of high (riding strength) but not exhausted
        composite = momentum + 0.35 * volume + 0.15 * drawdown_bonus

        scored.append({**r, "score": float(composite)})

    # Day-stable shuffle of ties
    seed = _daily_seed()
    scored.sort(key=lambda x: (-x["score"], (hash(x["ticker"]) ^ seed) & 0xFFFF))
    return scored[:top_n]
