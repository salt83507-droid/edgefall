# Edgefall Index

A self-updating desktop equity-analysis terminal with a Dillinger-inspired
visual style — pure black, electric red, monospace. Three tabs:

- **Quant Desk** — daily rotation, indicator dashboard, GBM Monte Carlo
  with 10/30/60-day expected values, written dossier per ticker.
- **Contract Watch** — federal contract feed from USAspending.gov, auto-
  tagged for **HIGH-IMPACT** awards likely to move the underlying stock.
- **Risk-On** — high-beta short-term speculative names with prominent
  risk metrics and 3/6/9/14-day expected values.

> Educational tool only. Not financial advice. Indicators, contract
> tags, and price projections are signals — not instructions.

---

## Two ways to run it

### A) Run from source (developers)

You need Python 3.10+ on your machine. Then double-click **`run.bat`**
(Windows) or `./run.sh` (macOS/Linux). The first launch creates a venv
and installs dependencies; subsequent launches are instant.

### B) Build a standalone application (to share with non-Python users)

This packages the app into a single binary your friends can run **without
Python installed**. You build the binary once on the same OS as the
target machine.

#### Windows → `EdgefallIndex.exe`

1. Make sure Python 3.10+ is installed (with "Add to PATH" ticked).
2. Double-click **`build_windows.bat`**.
3. Wait 2–5 minutes. The output appears at `dist\EdgefallIndex.exe`.
4. Send that single `.exe` to anyone on Windows 10/11 — they can
   double-click it directly. No Python needed on their side.

#### macOS → `EdgefallIndex.app`

1. Make sure Python 3.10+ is installed (`python3 --version`).
2. From Terminal:

   ```bash
   chmod +x build_mac.sh
   ./build_mac.sh
   ```

3. Wait 2–5 minutes. The output appears at `dist/EdgefallIndex.app`.
4. Drag it into `/Applications`, or zip and send to other Mac users.

> **Cross-compilation note.** Mac binaries must be built on a Mac, and
> Windows binaries must be built on Windows — that's a PyInstaller
> limitation, not a choice. If you only have one of the two platforms,
> ask a friend on the other one to run the corresponding build script,
> or use a cloud build service (GitHub Actions has free Windows + macOS
> runners that work for this).

> **macOS Gatekeeper.** First-launch prompt about an "unidentified
> developer" is normal for unsigned builds. Right-click → Open → Open
> to bypass it once, or run
> `xattr -dr com.apple.quarantine dist/EdgefallIndex.app`.

---

## Tabs in detail

### Quant Desk

Daily composite-momentum rotation on the left (~50 large-cap names,
deterministic per-day). Center: price chart with SMA20/SMA50, Bollinger
bands, and a 60-day GBM Monte Carlo cone (5/50/95 percentile). Below
the price label is a row of three **expected-value cards** — 10D, 30D,
60D — each showing expected price, percent change, and probability of
finishing above today's close. Right column: dossier with company
description, fundamentals, quant metrics (annualized return, vol,
Sharpe, beta vs SPY, RSI), why-it's-on-the-radar bullets, and recent
headlines.

### Contract Watch

Pulls procurement contracts from USAspending.gov filtered by NAICS code
for Defense / Medical / Tech sectors. Each award is auto-tagged by an
impact heuristic that uses *only metadata* (no per-row API calls):

- **HIGH-IMPACT** — small/mid-cap recipient + strategic agency (DARPA,
  Space Force, BARDA, NASA, IC) **or** narrative-theme keyword in scope
  (hypersonic, quantum, AI, autonomous, satellite, vaccine, full-rate
  production), plus meaningful absolute size. Full-width red banner on
  card and detail. Sorted to the top.
- **WATCH** — matched ticker with at least one elevated factor.
- **ROUTINE** — matched ticker, nothing notable.
- **NOISE** — unmatched private/foreign recipient.

Click any contract for the **Context Score** (0–100) — a deeper
analysis blending materiality vs. revenue, strategic agency tier,
multi-year horizon, and narrative themes — plus the **Speculative
Thesis** section explaining contract-driven angles for why this award
itself could rerate the equity (customer validation, materiality
re-rating, recurring-revenue tail, production-phase margin, IDIQ
ceiling optionality, narrative tailwind).

### Risk-On

Universe of ~50 high-beta, high-volatility names (AI/quantum micro-caps,
crypto-adjacent miners, biotech with binary catalysts, EVs, meme,
high-beta semis). Each gets a **Risk Score 0–100** built from
annualized volatility, max 12-month drawdown, beta vs SPY, and 30-day
swing range — explicitly framed as a *sizing signal, not a directional
one*. Sortable by Risk Score, Volatility, 5d Return, Beta, Drawdown, or
RSI.

Click any name for the detail view, which opens with a red
high-risk banner, then shows a row of **short-horizon expected-value
cards** — 3D, 6D, 9D, 14D — each with expected price, percent change,
P(up), and the 5/95 plausibility band. Below: setup classification
(Stretched/Late Momentum, Oversold/Bounce Watch, etc.), a metrics grid
where over-threshold values turn red, pattern observation notes, and a
hard warning to size positions for a -50% adverse scenario.

---

## Files

| File | Purpose |
|---|---|
| `app.py` | Main UI — three tabs, Tron-inspired styling |
| `data_fetcher.py` | yfinance wrapper with per-day disk cache |
| `analysis.py` | Indicators, risk metrics, GBM Monte Carlo |
| `screener.py` | Daily rotation composite scoring |
| `summary.py` | Plain-English dossiers |
| `contracts.py` | USAspending client, ticker matching, impact tag, context score, speculative thesis |
| `risk.py` | High-vol universe, risk score, short-term thesis |
| `requirements.txt` | Python dependencies |
| `run.bat` / `run.sh` | Run from source (dev) |
| `build_windows.bat` | Build standalone `.exe` |
| `build_mac.sh` | Build standalone `.app` |

## Methodology sources

Geometric Brownian Motion Monte Carlo (Hull, *Options, Futures, and
Other Derivatives*); CAPM beta (Sharpe 1964); momentum factor (Jegadeesh
& Titman 1993, *J. Finance*); RSI (Wilder 1978); MACD (Appel 1979);
Bollinger Bands (Bollinger, 1980s). Standard CFA Level I / FNCE 100 /
Sloan 15.401 syllabus material.

## Disclaimer

This program is for research and learning. It does not constitute
investment advice, a recommendation, or a solicitation to buy or sell
any security. Markets are uncertain. Past performance does not predict
future results. Do your own research and, if you need personalized
advice, talk to a licensed financial professional.
