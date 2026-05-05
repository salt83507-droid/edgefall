"""
Data fetcher with on-disk daily caching.

We use yfinance (free, no API key) for prices, fundamentals, and company info.
A simple JSON+pickle cache makes the app feel instant after the first daily load
and means we only hit the network once per ticker per calendar day.
"""

from __future__ import annotations

import os
import json
import pickle
import datetime as dt
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf


CACHE_DIR = Path.home() / ".noir_stocks_cache"
CACHE_DIR.mkdir(exist_ok=True)


def _today_key() -> str:
    return dt.date.today().isoformat()


def _cache_path(kind: str, ticker: str) -> Path:
    safe = ticker.replace("/", "_").replace("\\", "_").upper()
    return CACHE_DIR / f"{kind}_{safe}_{_today_key()}.pkl"


def _load_cache(path: Path):
    if path.exists():
        try:
            with open(path, "rb") as f:
                return pickle.load(f)
        except Exception:
            return None
    return None


def _save_cache(path: Path, obj) -> None:
    try:
        with open(path, "wb") as f:
            pickle.dump(obj, f)
    except Exception:
        pass


def get_history(ticker: str, period: str = "2y", interval: str = "1d") -> pd.DataFrame:
    """Daily OHLCV for a ticker. Cached per-day."""
    path = _cache_path(f"hist_{period}_{interval}", ticker)
    cached = _load_cache(path)
    if cached is not None:
        return cached
    try:
        df = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=True)
    except Exception:
        df = pd.DataFrame()
    if not df.empty:
        df.index = pd.to_datetime(df.index)
        _save_cache(path, df)
    return df


def get_info(ticker: str) -> dict:
    """Company info / fundamentals. Cached per-day."""
    path = _cache_path("info", ticker)
    cached = _load_cache(path)
    if cached is not None:
        return cached
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:
        info = {}
    if info:
        _save_cache(path, info)
    return info


def get_news(ticker: str, limit: int = 5) -> list[dict]:
    """Recent news headlines for the ticker (yfinance pulls these from Yahoo)."""
    path = _cache_path("news", ticker)
    cached = _load_cache(path)
    if cached is not None:
        return cached[:limit]
    try:
        news = yf.Ticker(ticker).news or []
    except Exception:
        news = []
    cleaned = []
    for n in news:
        # yfinance news shape changed across versions; handle both
        content = n.get("content", n)
        title = content.get("title") or n.get("title")
        publisher = (
            content.get("provider", {}).get("displayName")
            if isinstance(content.get("provider"), dict)
            else n.get("publisher")
        )
        link = (
            content.get("canonicalUrl", {}).get("url")
            if isinstance(content.get("canonicalUrl"), dict)
            else n.get("link")
        )
        if title:
            cleaned.append({"title": title, "publisher": publisher or "", "link": link or ""})
    if cleaned:
        _save_cache(path, cleaned)
    return cleaned[:limit]


# A curated screening universe. We screen these daily for the rotation panel.
# Mix of mega-caps, popular momentum names, and a few defensive picks so the
# rotation shows variety regardless of market regime.
SCREEN_UNIVERSE = [
    # Mega-cap tech
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "ORCL", "CRM",
    # Semis / hardware
    "AMD", "INTC", "QCOM", "TSM", "ASML", "MU", "ARM",
    # Software / cloud
    "PLTR", "SNOW", "NET", "DDOG", "CRWD", "PANW", "NOW",
    # Consumer
    "COST", "WMT", "HD", "NKE", "SBUX", "MCD", "DIS",
    # Finance
    "JPM", "BAC", "GS", "MS", "V", "MA", "BRK-B",
    # Health
    "LLY", "UNH", "JNJ", "PFE", "MRNA", "ABBV",
    # Industrials / energy
    "BA", "CAT", "GE", "XOM", "CVX",
    # ETFs as benchmarks
    "SPY", "QQQ", "DIA", "IWM",
]


def screen_universe_quick() -> list[dict]:
    """
    Cheap daily screen across SCREEN_UNIVERSE.

    For each ticker we pull recent history (cached) and compute a few momentum
    and volume features, then rank. This is the engine behind the daily
    'up and coming' rotation panel.
    """
    rows = []
    for t in SCREEN_UNIVERSE:
        df = get_history(t, period="6mo", interval="1d")
        if df.empty or len(df) < 30:
            continue
        close = df["Close"]
        vol = df["Volume"]
        last = float(close.iloc[-1])

        ret_5 = float(close.pct_change(5).iloc[-1]) if len(close) > 5 else 0.0
        ret_20 = float(close.pct_change(20).iloc[-1]) if len(close) > 20 else 0.0
        ret_60 = float(close.pct_change(60).iloc[-1]) if len(close) > 60 else 0.0

        vol_ratio = float(vol.iloc[-5:].mean() / max(vol.iloc[-30:].mean(), 1))

        # 52w-ish proxy from 6mo window
        high_window = float(close.max())
        pct_off_high = (last - high_window) / high_window

        rows.append(
            {
                "ticker": t,
                "last": last,
                "ret_5": ret_5,
                "ret_20": ret_20,
                "ret_60": ret_60,
                "vol_ratio": vol_ratio,
                "pct_off_high": pct_off_high,
            }
        )
    return rows
