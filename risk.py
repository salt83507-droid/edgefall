"""
Risk-on universe and short-term speculative scoring.

This module surfaces high-beta, high-volatility names where short-term
moves are large in either direction. Risk metrics are computed prominently
so the user sees DOWNSIDE clearly:
  - Annualized volatility
  - Maximum 12-month drawdown
  - Beta vs. SPY
  - 30-day high-low swing as % of price
  - RSI overextension flag
  - Composite Risk Score (0-100, higher = more volatile, NOT a buy signal)

The 'risk score' is intentionally separate from any return forecast.
A high score means high blast radius — both upside and downside — and
is a sizing signal, not a directional one.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from data_fetcher import get_history
from analysis import rsi, sma


# Curated high-beta / high-volatility universe. Mix of momentum, biotech,
# crypto-adjacent, EV, meme, and small-cap defense/space names.
RISK_UNIVERSE = [
    # AI / quantum micro-momentum
    "BBAI", "AI", "IONQ", "RGTI", "QBTS", "SOUN", "PATH",
    # Drones / autonomy / defense small-caps
    "RCAT", "ONDS", "KTOS", "AVAV", "ACHR", "JOBY", "EH",
    # Space / launch
    "RKLB", "BKSY", "PL", "SPIR", "LUNR", "ASTS", "SATS",
    # Crypto / mining / leveraged
    "MSTR", "COIN", "MARA", "RIOT", "CLSK", "HUT", "BITF",
    # EVs / consumer story
    "RIVN", "LCID", "NIO", "XPEV", "LI", "NKLA",
    # Biotech (binary catalyst risk)
    "MRNA", "BNTX", "NVAX", "SAVA", "OCGN", "ANIX", "DVAX",
    "CRSP", "BEAM", "NTLA", "SRPT", "EDIT",
    # Meme / momentum
    "GME", "AMC", "SOFI", "HOOD", "DJT", "TLRY", "CGC",
    # High-beta semis
    "SMCI", "ARM", "WOLF", "CRDO", "MU",
]


def _max_drawdown(close: pd.Series) -> float:
    if close.empty:
        return 0.0
    running_max = close.cummax()
    dd = (close - running_max) / running_max
    return float(dd.min())


def screen_risk_universe() -> list[dict]:
    """Compute risk metrics for the full universe. Cached upstream by data_fetcher."""
    spy = get_history("SPY", period="1y", interval="1d")
    if not spy.empty:
        spy_log_ret = np.log(spy["Close"] / spy["Close"].shift(1)).dropna()
    else:
        spy_log_ret = pd.Series(dtype=float)

    rows: list[dict] = []
    for ticker in RISK_UNIVERSE:
        df = get_history(ticker, period="1y", interval="1d")
        if df.empty or len(df) < 30:
            continue
        close = df["Close"]
        log_ret = np.log(close / close.shift(1)).dropna()
        last = float(close.iloc[-1])

        ann_vol = float(log_ret.std() * np.sqrt(252)) if len(log_ret) > 1 else 0.0
        max_dd = _max_drawdown(close)

        beta = float("nan")
        if not spy_log_ret.empty:
            joint = pd.concat([spy_log_ret, log_ret], axis=1).dropna()
            if len(joint) > 20:
                cov = np.cov(joint.iloc[:, 0], joint.iloc[:, 1])[0, 1]
                var = np.var(joint.iloc[:, 0])
                beta = float(cov / var) if var > 0 else float("nan")

        ret_5 = float(close.pct_change(5).iloc[-1]) if len(close) > 5 else 0.0
        ret_20 = float(close.pct_change(20).iloc[-1]) if len(close) > 20 else 0.0

        recent = close.iloc[-30:]
        swing_30d = float((recent.max() - recent.min()) / recent.min()) if recent.min() > 0 else 0.0

        rsi_now = float(rsi(close).iloc[-1])

        # --- Risk score 0-100 (higher = riskier, NOT a buy signal) ---
        score = 0
        if ann_vol > 1.0:
            score += 35
        elif ann_vol > 0.6:
            score += 25
        elif ann_vol > 0.4:
            score += 15
        else:
            score += 5

        if not np.isnan(beta):
            if beta > 2.0:
                score += 25
            elif beta > 1.5:
                score += 18
            elif beta > 1.0:
                score += 10

        if max_dd < -0.5:
            score += 20
        elif max_dd < -0.3:
            score += 12
        elif max_dd < -0.15:
            score += 6

        if swing_30d > 0.5:
            score += 15
        elif swing_30d > 0.3:
            score += 10
        elif swing_30d > 0.15:
            score += 5

        rows.append({
            "ticker": ticker,
            "last": last,
            "ann_vol": ann_vol,
            "max_dd": max_dd,
            "beta": beta,
            "ret_5": ret_5,
            "ret_20": ret_20,
            "swing_30d": swing_30d,
            "rsi": rsi_now,
            "risk_score": min(100, score),
        })

    rows.sort(key=lambda r: -r["risk_score"])
    return rows


def short_term_thesis(row: dict) -> dict:
    """
    Build a SHORT-TERM speculative read for a single risk-on name.

    This is *not* a buy/sell call. It surfaces what short-term traders
    typically watch for at this point in the price action, alongside
    explicit downside-scenario language so the user is sized for losses.
    """
    notes: list[str] = []
    setup_type = "Mixed"

    rsi_now = row.get("rsi", 50)
    ret_5 = row.get("ret_5", 0)
    swing = row.get("swing_30d", 0)
    beta = row.get("beta", float("nan"))
    vol = row.get("ann_vol", 0)
    dd = row.get("max_dd", 0)

    # Setup interpretation
    if rsi_now > 70 and ret_5 > 0.10:
        setup_type = "Stretched / Late Momentum"
        notes.append(
            f"RSI {rsi_now:.0f} with a 5-day move of {ret_5*100:+.1f}% — "
            "the name is in stretched-momentum territory. Short-term traders "
            "often look for gap-fills or volume-divergence reversals here."
        )
    elif rsi_now < 30 and ret_5 < -0.05:
        setup_type = "Oversold / Bounce Watch"
        notes.append(
            f"RSI {rsi_now:.0f} with a 5-day move of {ret_5*100:+.1f}% — "
            "oversold conditions. Relief bounces often appear, but oversold "
            "regimes can persist deep into genuine downtrends."
        )
    elif rsi_now > 65:
        setup_type = "Elevated Momentum"
        notes.append(f"RSI {rsi_now:.0f} — in elevated momentum zone, near risk of reversal.")
    elif rsi_now < 35:
        setup_type = "Weak / Compressed"
        notes.append(f"RSI {rsi_now:.0f} — pressured. Look for stabilization signals before exposure.")
    else:
        notes.append(f"RSI {rsi_now:.0f} — neutral momentum.")

    # Volatility context
    if vol > 1.0:
        notes.append(
            f"Annualized vol {vol*100:.0f}%. Daily 5-10% swings are normal — "
            "stops set tight will be triggered by noise."
        )
    elif vol > 0.6:
        notes.append(f"Annualized vol {vol*100:.0f}% — well above market. Position sizing matters here more than entry price.")

    # Beta amplification
    if not np.isnan(beta) and beta > 1.5:
        notes.append(
            f"Beta {beta:.2f}. The name moves roughly {beta:.1f}x the broad "
            "market — macro events (CPI prints, Fed decisions) amplify."
        )

    # Range / swing context
    if swing > 0.4:
        notes.append(
            f"30-day high-low swing {swing*100:.0f}%. Round-trip price action "
            "this large makes timing entries/exits as important as the thesis itself."
        )

    # Drawdown context
    if dd < -0.5:
        notes.append(
            f"Max 12-mo drawdown {dd*100:.0f}%. The name has lost more than half "
            "its value within the year — capital preservation is the dominant risk."
        )
    elif dd < -0.3:
        notes.append(f"Max 12-mo drawdown {dd*100:.0f}% — meaningful prior pain.")

    return {
        "setup": setup_type,
        "notes": notes,
        "warning": (
            "SHORT-TERM SPECULATION. These names can lose 20%+ in a single session "
            "and 50%+ in a month. Size positions to a -50% adverse-scenario. Use "
            "stops. This is not investment advice — these are pattern observations."
        ),
    }
