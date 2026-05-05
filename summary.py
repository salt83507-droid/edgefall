"""
Plain-English written summaries for each ticker.

We pull the company description and key fundamentals from yfinance (which
ultimately sources Yahoo Finance / Refinitiv) and add a quantitative
narrative built from our own indicators. We also surface up to three recent
news headlines as light context. No 'buy'/'sell' wording — purely a digest.
"""

from __future__ import annotations

import textwrap
from typing import Optional

import numpy as np
import pandas as pd

from data_fetcher import get_info, get_news
from analysis import (
    rsi,
    sma,
    macd,
    annualized_return,
    annualized_volatility,
    sharpe_ratio,
    beta_vs,
)


def _fmt_pct(x: float) -> str:
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return "—"
    return f"{x*100:+.1f}%"


def _fmt_num(x, default="—"):
    if x is None:
        return default
    try:
        if isinstance(x, float) and (np.isnan(x) or np.isinf(x)):
            return default
        if abs(x) >= 1e12:
            return f"{x/1e12:.2f}T"
        if abs(x) >= 1e9:
            return f"{x/1e9:.2f}B"
        if abs(x) >= 1e6:
            return f"{x/1e6:.2f}M"
        return f"{x:,.2f}"
    except Exception:
        return str(x)


def write_summary(
    ticker: str,
    df: pd.DataFrame,
    benchmark_df: Optional[pd.DataFrame] = None,
) -> dict:
    """Build the dict the UI consumes for the Summary panel."""
    info = get_info(ticker)
    news = get_news(ticker, limit=3)

    name = info.get("longName") or info.get("shortName") or ticker
    sector = info.get("sector") or "—"
    industry = info.get("industry") or "—"
    summary_text = (info.get("longBusinessSummary") or "").strip()
    if len(summary_text) > 900:
        summary_text = summary_text[:900].rsplit(" ", 1)[0] + "…"

    market_cap = info.get("marketCap")
    pe = info.get("trailingPE") or info.get("forwardPE")
    div_yield = info.get("dividendYield")
    profit_margin = info.get("profitMargins")
    revenue_growth = info.get("revenueGrowth")
    fifty_two_low = info.get("fiftyTwoWeekLow")
    fifty_two_high = info.get("fiftyTwoWeekHigh")

    close = df["Close"]
    log_ret = np.log(close / close.shift(1)).dropna()
    ann_ret = annualized_return(log_ret)
    ann_vol = annualized_volatility(log_ret)
    sr = sharpe_ratio(log_ret)

    bench_beta = float("nan")
    if benchmark_df is not None and not benchmark_df.empty:
        bench_ret = np.log(benchmark_df["Close"] / benchmark_df["Close"].shift(1)).dropna()
        bench_beta = beta_vs(bench_ret, log_ret)

    rsi_now = float(rsi(close).iloc[-1])
    last = float(close.iloc[-1])
    s20 = float(sma(close, 20).iloc[-1])
    s50 = float(sma(close, 50).iloc[-1])

    # Why it might be interesting — composed from observed signals.
    reasons = []
    if rsi_now < 35:
        reasons.append("RSI sits in oversold territory, where mean-reversion strategies historically look for setups.")
    elif rsi_now > 65 and last > s20 > s50:
        reasons.append("Strong momentum stack — price riding above its short and intermediate moving averages.")
    if revenue_growth and revenue_growth > 0.10:
        reasons.append(f"Trailing revenue growth of {revenue_growth*100:.0f}% — well above the broad market median.")
    if profit_margin and profit_margin > 0.15:
        reasons.append(f"Profit margins around {profit_margin*100:.0f}% indicate operating leverage.")
    if pe and pe < 18 and revenue_growth and revenue_growth > 0.05:
        reasons.append(f"Trailing P/E near {pe:.1f} alongside positive growth — a classic GARP signature.")
    if not reasons:
        reasons.append("Included in the rotation as a benchmark or for sector diversification.")

    return {
        "ticker": ticker,
        "name": name,
        "sector": sector,
        "industry": industry,
        "description": summary_text or "No company description available.",
        "fundamentals": {
            "Market Cap": _fmt_num(market_cap),
            "P/E": _fmt_num(pe),
            "Div Yield": _fmt_pct(div_yield) if isinstance(div_yield, (int, float)) else "—",
            "Profit Margin": _fmt_pct(profit_margin) if isinstance(profit_margin, (int, float)) else "—",
            "Rev Growth": _fmt_pct(revenue_growth) if isinstance(revenue_growth, (int, float)) else "—",
            "52w Low": _fmt_num(fifty_two_low),
            "52w High": _fmt_num(fifty_two_high),
        },
        "quant": {
            "Last": f"{last:,.2f}",
            "Ann. Return": _fmt_pct(ann_ret),
            "Ann. Vol": _fmt_pct(ann_vol),
            "Sharpe (rf=4.5%)": f"{sr:.2f}",
            "Beta vs SPY": f"{bench_beta:.2f}" if not np.isnan(bench_beta) else "—",
            "RSI(14)": f"{rsi_now:.0f}",
        },
        "reasons": reasons,
        "news": news,
    }
