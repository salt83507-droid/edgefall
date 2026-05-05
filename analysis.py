"""
Quantitative analysis primitives.

The methods here are textbook material from undergraduate / MBA finance
courses (Bodie/Kane/Marcus, Hull, Damodaran's NYU Stern lectures). Each
function is annotated with the source category so the UI can render
'Methodology' citations.

Nothing in this file constitutes financial advice. Indicators are signals,
not instructions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


# ----------------------------- Technical indicators -----------------------------
# Reference: J. Murphy, "Technical Analysis of the Financial Markets" (NYIF);
# also covered in CFA Level I curriculum, Reading on Technical Analysis.

def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window).mean()


def ema(series: pd.Series, window: int) -> pd.Series:
    return series.ewm(span=window, adjust=False).mean()


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder, 1978). >70 overbought, <30 oversold."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Moving Average Convergence Divergence (Appel, 1979)."""
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def bollinger(series: pd.Series, window: int = 20, n_std: float = 2.0):
    """Bollinger Bands (Bollinger, 1980s)."""
    mid = sma(series, window)
    sd = series.rolling(window).std()
    return mid, mid + n_std * sd, mid - n_std * sd


# ----------------------------- Risk metrics -----------------------------
# Reference: Sharpe (1966), CAPM (Sharpe 1964 / Lintner 1965); standard in
# Wharton FNCE 100 and MIT Sloan 15.401 problem sets.

def annualized_volatility(returns: pd.Series, periods_per_year: int = 252) -> float:
    return float(returns.std() * np.sqrt(periods_per_year))


def annualized_return(returns: pd.Series, periods_per_year: int = 252) -> float:
    return float(returns.mean() * periods_per_year)


def sharpe_ratio(returns: pd.Series, rf: float = 0.045, periods_per_year: int = 252) -> float:
    ann_ret = annualized_return(returns, periods_per_year)
    ann_vol = annualized_volatility(returns, periods_per_year)
    if ann_vol == 0:
        return 0.0
    return float((ann_ret - rf) / ann_vol)


def beta_vs(benchmark_returns: pd.Series, asset_returns: pd.Series) -> float:
    """CAPM beta. Aligns the two series first."""
    df = pd.concat([benchmark_returns, asset_returns], axis=1).dropna()
    if len(df) < 20:
        return float("nan")
    cov = np.cov(df.iloc[:, 0], df.iloc[:, 1])[0, 1]
    var = np.var(df.iloc[:, 0])
    return float(cov / var) if var > 0 else float("nan")


# ----------------------------- Forecasting -----------------------------
# Reference: Hull, "Options, Futures, and Other Derivatives" Ch. 14
# (geometric Brownian motion). This is the same diffusion that underpins
# Black-Scholes and is the standard 'plain vanilla' Monte Carlo taught in
# Columbia IEOR and Princeton ORF coursework.

@dataclass
class MonteCarloResult:
    horizon_days: int
    paths: np.ndarray  # shape (n_paths, horizon_days+1)
    p5: np.ndarray
    p50: np.ndarray
    p95: np.ndarray
    expected: float
    prob_up: float


def monte_carlo_gbm(
    closes: pd.Series,
    horizon_days: int = 60,
    n_paths: int = 2000,
    seed: int = 42,
) -> MonteCarloResult:
    """
    Geometric Brownian Motion price simulation.

    dS = mu*S*dt + sigma*S*dW

    mu, sigma are estimated from the trailing log-returns. We return the
    5/50/95 percentile bands so the UI can shade an uncertainty cone.

    This is a *statistical projection*, not a forecast. Real markets have
    fat tails, jumps, and regime changes that GBM does not capture.
    """
    rng = np.random.default_rng(seed)
    log_returns = np.log(closes / closes.shift(1)).dropna()
    if len(log_returns) < 30:
        raise ValueError("Not enough history for Monte Carlo.")

    mu = float(log_returns.mean())
    sigma = float(log_returns.std())
    s0 = float(closes.iloc[-1])

    dt = 1.0
    shocks = rng.standard_normal((n_paths, horizon_days))
    increments = (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * shocks
    log_paths = np.cumsum(increments, axis=1)
    paths = s0 * np.exp(np.concatenate([np.zeros((n_paths, 1)), log_paths], axis=1))

    p5 = np.percentile(paths, 5, axis=0)
    p50 = np.percentile(paths, 50, axis=0)
    p95 = np.percentile(paths, 95, axis=0)
    expected = float(paths[:, -1].mean())
    prob_up = float((paths[:, -1] > s0).mean())

    return MonteCarloResult(
        horizon_days=horizon_days,
        paths=paths,
        p5=p5,
        p50=p50,
        p95=p95,
        expected=expected,
        prob_up=prob_up,
    )


# ----------------------------- Signal aggregation -----------------------------

@dataclass
class SignalReport:
    headline: str       # "Caution", "Neutral", "Constructive"
    color: str          # hex
    bullets: list[str]


def build_signal_report(df: pd.DataFrame) -> SignalReport:
    """
    Aggregate a few classic indicators into a *neutral-language* read.

    We deliberately avoid words like 'buy' or 'sell'. Instead the panel says
    things like 'RSI in overbought territory' and lets the user decide.
    """
    close = df["Close"]
    rsi_now = float(rsi(close).iloc[-1])
    sma20 = float(sma(close, 20).iloc[-1])
    sma50 = float(sma(close, 50).iloc[-1])
    sma200 = float(sma(close, 200).iloc[-1]) if len(close) >= 200 else float("nan")
    macd_line, signal_line, hist = macd(close)
    macd_now = float(macd_line.iloc[-1])
    sig_now = float(signal_line.iloc[-1])
    last = float(close.iloc[-1])

    bullets = []
    cautions = 0
    constructives = 0

    # RSI
    if rsi_now >= 70:
        bullets.append(f"RSI {rsi_now:.0f} — overbought zone (Wilder, 1978). Historically associated with short-term mean reversion.")
        cautions += 1
    elif rsi_now <= 30:
        bullets.append(f"RSI {rsi_now:.0f} — oversold zone. Often precedes a relief bounce, but can persist in downtrends.")
        constructives += 1
    else:
        bullets.append(f"RSI {rsi_now:.0f} — neutral momentum.")

    # Trend stack
    if not np.isnan(sma200):
        if last > sma50 > sma200:
            bullets.append("Price above 50d above 200d — classic uptrend stack.")
            constructives += 1
        elif last < sma50 < sma200:
            bullets.append("Price below 50d below 200d — classic downtrend stack.")
            cautions += 1
        else:
            bullets.append("Mixed trend — moving averages are not aligned.")

    # MACD
    if macd_now > sig_now and hist.iloc[-1] > hist.iloc[-2]:
        bullets.append("MACD above signal line and rising — momentum tailwind.")
        constructives += 1
    elif macd_now < sig_now and hist.iloc[-1] < hist.iloc[-2]:
        bullets.append("MACD below signal line and falling — momentum headwind.")
        cautions += 1

    # Distance from 20d
    pct_from_20 = (last - sma20) / sma20 if sma20 else 0
    if abs(pct_from_20) > 0.10:
        side = "above" if pct_from_20 > 0 else "below"
        bullets.append(f"Price is {abs(pct_from_20)*100:.1f}% {side} its 20-day mean — stretched.")
        cautions += 1

    # Headline
    if cautions - constructives >= 2:
        headline, color = "Caution Signals", "#a83232"
    elif constructives - cautions >= 2:
        headline, color = "Constructive Signals", "#5c8a4f"
    else:
        headline, color = "Mixed Signals", "#c9a227"

    return SignalReport(headline=headline, color=color, bullets=bullets)
