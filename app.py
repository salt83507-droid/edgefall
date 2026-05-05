"""
Edgefall Index — desktop application.

Two tabs:
  · QUANT DESK     — daily rotation, indicator dashboard, GBM Monte Carlo,
                     written dossier per ticker
  · CONTRACT WATCH — USAspending.gov feed of recent federal contracts to
                     small-to-mid-cap defense / medical / tech companies,
                     with a contextual score (materiality × strategic
                     customer × multi-year horizon × narrative theme)

Disclaimer: educational/analytical tool only. Not financial advice.
Indicators and contract context are signals, not instructions.
"""

from __future__ import annotations

import datetime as dt
import threading
import webbrowser
from typing import Optional

import customtkinter as ctk
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import numpy as np
import pandas as pd

from data_fetcher import get_history, get_info
from analysis import (
    sma, ema, rsi, macd, bollinger, monte_carlo_gbm, build_signal_report,
)
from screener import daily_rotation
from summary import write_summary
from contracts import (
    fetch_contracts, match_ticker, score_contract, speculative_thesis,
    quick_impact_tag, is_small_mid, MEGA_CAPS,
)
from risk import screen_risk_universe, short_term_thesis


# --- Palette: black / electric red / white (Dillinger-inspired, minimal) ---
BG          = "#000000"   # pure black
PANEL       = "#0a0a0a"
PANEL_2     = "#141414"
BORDER      = "#3a0c0c"   # dim red border (was grey)
TEXT        = "#f0f0f0"   # near-white
MUTED       = "#5a5a5a"
ACCENT      = "#ff2020"   # electric red (was oxblood)
GOLD        = "#ff6464"   # light hot-red, retains role as secondary accent
GREEN       = "#3a9a55"
RED         = "#ff3030"
GRID        = "#1a0505"   # very faint red-tinted grid

# Typography — monospace tech feel
HEAD_FONT   = "Consolas"
BODY_FONT   = "Consolas"


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


def _apply_noir_axes(ax, title: str = ""):
    ax.set_facecolor(PANEL)
    for spine in ax.spines.values():
        spine.set_color(BORDER)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.grid(True, color=GRID, linewidth=0.5, linestyle="-")
    ax.title.set_color(TEXT)
    if title:
        ax.set_title(title, color=TEXT, fontsize=10, loc="left", pad=8)
    ax.xaxis.label.set_color(MUTED)
    ax.yaxis.label.set_color(MUTED)


def _make_figure(figsize=(7, 4)):
    return Figure(figsize=figsize, dpi=100, facecolor=PANEL)


def _fmt_money(amount: float) -> str:
    if amount >= 1e9:
        return f"${amount/1e9:.2f}B"
    if amount >= 1e6:
        return f"${amount/1e6:.1f}M"
    if amount >= 1e3:
        return f"${amount/1e3:.0f}K"
    return f"${amount:,.0f}"


# --- App ------------------------------------------------------------------
class EdgefallIndexApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("EDGEFALL INDEX")
        self.geometry("1480x920")
        self.configure(fg_color=BG)

        # State for the contracts tab
        self._contract_results: list[dict] = []
        self._selected_contract: Optional[dict] = None
        self._contract_filters = {
            "defense": True,
            "medical": True,
            "tech": True,
            "min_amount": 5_000_000,
            "days_back": 180,
        }

        self._build_layout()
        self._refresh_rotation()
        self.after(100, lambda: self._load_ticker("AAPL"))
        self.after(400, self._refresh_contracts)

    # ============================ LAYOUT ============================
    def _build_layout(self):
        # Top bar
        top = ctk.CTkFrame(self, fg_color=PANEL_2, corner_radius=0, height=54)
        top.pack(side="top", fill="x")
        top.pack_propagate(False)

        # Brand mark — red bracket + name
        brand = ctk.CTkFrame(top, fg_color=PANEL_2)
        brand.pack(side="left", padx=18)
        ctk.CTkLabel(
            brand, text="▎", text_color=ACCENT,
            font=ctk.CTkFont(family=HEAD_FONT, size=22, weight="bold"),
        ).pack(side="left", padx=(0, 4))
        ctk.CTkLabel(
            brand, text="EDGEFALL // INDEX", text_color=TEXT,
            font=ctk.CTkFont(family=HEAD_FONT, size=18, weight="bold"),
        ).pack(side="left")

        sub = ctk.CTkLabel(
            top, text=f"  [ {dt.date.today():%Y.%m.%d} ]",
            text_color=ACCENT,
            font=ctk.CTkFont(family=HEAD_FONT, size=11),
        )
        sub.pack(side="left")

        self.search_entry = ctk.CTkEntry(
            top, width=180, placeholder_text="ticker (e.g. NVDA)",
            fg_color=PANEL, border_color=BORDER, text_color=TEXT,
        )
        self.search_entry.pack(side="right", padx=(0, 14), pady=10)
        self.search_entry.bind("<Return>", lambda e: self._on_search())

        ctk.CTkButton(
            top, text="ANALYZE", width=90,
            fg_color=ACCENT, hover_color="#6a1414", text_color=TEXT,
            command=self._on_search, font=ctk.CTkFont(weight="bold"),
        ).pack(side="right", padx=(0, 8))

        ctk.CTkButton(
            top, text="REFRESH ROTATION", width=140,
            fg_color=PANEL, hover_color=BORDER, text_color=GOLD,
            command=self._refresh_rotation,
        ).pack(side="right", padx=(0, 8))

        # 1px red divider under the top bar — sharp Tron-grid edge
        divider = ctk.CTkFrame(self, fg_color=ACCENT, height=1, corner_radius=0)
        divider.pack(side="top", fill="x")

        # --- Tab system ---
        self.tabs = ctk.CTkTabview(
            self, fg_color=BG, segmented_button_fg_color=PANEL_2,
            segmented_button_selected_color=ACCENT,
            segmented_button_selected_hover_color="#6a1414",
            segmented_button_unselected_color=PANEL,
            segmented_button_unselected_hover_color=BORDER,
            text_color=TEXT, corner_radius=0, border_width=0,
        )
        self.tabs.pack(side="top", fill="both", expand=True, padx=0, pady=0)
        self.tabs.add("QUANT DESK")
        self.tabs.add("CONTRACT WATCH")
        self.tabs.add("RISK-ON")

        self._build_quant_tab(self.tabs.tab("QUANT DESK"))
        self._build_contracts_tab(self.tabs.tab("CONTRACT WATCH"))
        self._build_risk_tab(self.tabs.tab("RISK-ON"))

        disclaimer = ctk.CTkLabel(
            self,
            text=(
                "  EDUCATIONAL TOOL  ·  Data: Yahoo Finance via yfinance & USAspending.gov  "
                "·  Methods: GBM Monte Carlo (Hull), CAPM Beta (Sharpe), "
                "RSI (Wilder), MACD (Appel), Bollinger Bands  "
                "·  Not financial advice."
            ),
            text_color=MUTED, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=10, slant="italic"),
        )
        disclaimer.pack(side="bottom", fill="x", padx=10, pady=4)

    # ============================ QUANT DESK TAB ============================
    def _build_quant_tab(self, parent):
        body = ctk.CTkFrame(parent, fg_color=BG, corner_radius=0)
        body.pack(side="top", fill="both", expand=True)

        self.left = ctk.CTkFrame(body, fg_color=PANEL, width=240, corner_radius=0)
        self.left.pack(side="left", fill="y")
        self.left.pack_propagate(False)
        self._build_rotation_panel(self.left)

        self.center = ctk.CTkFrame(body, fg_color=BG, corner_radius=0)
        self.center.pack(side="left", fill="both", expand=True)

        self.right = ctk.CTkFrame(body, fg_color=PANEL, width=420, corner_radius=0)
        self.right.pack(side="right", fill="y")
        self.right.pack_propagate(False)
        self._build_summary_panel(self.right)

        self._build_charts(self.center)

    def _build_rotation_panel(self, parent):
        ctk.CTkLabel(
            parent, text="DAILY ROTATION", text_color=GOLD, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=13, weight="bold"),
        ).pack(fill="x", padx=14, pady=(14, 2))
        ctk.CTkLabel(
            parent, text="ranked by composite momentum",
            text_color=MUTED, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=10, slant="italic"),
        ).pack(fill="x", padx=14, pady=(0, 10))

        self.rotation_status = ctk.CTkLabel(
            parent, text="loading…", text_color=MUTED, anchor="w",
            font=ctk.CTkFont(size=11),
        )
        self.rotation_status.pack(fill="x", padx=14, pady=(0, 8))

        self.rotation_container = ctk.CTkScrollableFrame(
            parent, fg_color=PANEL,
            scrollbar_button_color=BORDER, scrollbar_button_hover_color=ACCENT,
        )
        self.rotation_container.pack(fill="both", expand=True, padx=8, pady=(0, 12))

    def _refresh_rotation(self):
        self.rotation_status.configure(text="screening universe…")
        for w in self.rotation_container.winfo_children():
            w.destroy()
        threading.Thread(target=self._do_screen, daemon=True).start()

    def _do_screen(self):
        try:
            picks = daily_rotation(top_n=8)
        except Exception:
            picks = []
        self.after(0, lambda: self._render_rotation(picks))

    def _render_rotation(self, picks):
        if not picks:
            self.rotation_status.configure(text="no data — check connection")
            return
        self.rotation_status.configure(text=f"{len(picks)} picks · {dt.date.today():%b %d}")
        for p in picks:
            card = ctk.CTkFrame(self.rotation_container, fg_color=PANEL_2, corner_radius=0)
            card.pack(fill="x", padx=4, pady=4)
            top_row = ctk.CTkFrame(card, fg_color=PANEL_2)
            top_row.pack(fill="x", padx=10, pady=(8, 0))
            ctk.CTkLabel(
                top_row, text=p["ticker"], text_color=TEXT, anchor="w",
                font=ctk.CTkFont(family=HEAD_FONT, size=14, weight="bold"),
            ).pack(side="left")
            ctk.CTkLabel(
                top_row, text=f"{p['score']:+.2f}", text_color=GOLD,
                font=ctk.CTkFont(size=11),
            ).pack(side="right")

            ret_color = GREEN if p["ret_20"] >= 0 else RED
            ctk.CTkLabel(
                card,
                text=f"${p['last']:,.2f}  ·  20d {p['ret_20']*100:+.1f}%",
                text_color=ret_color, anchor="w", font=ctk.CTkFont(size=11),
            ).pack(fill="x", padx=10, pady=(0, 2))
            ctk.CTkLabel(
                card, text=f"vol {p['vol_ratio']:.2f}× avg",
                text_color=MUTED, anchor="w",
                font=ctk.CTkFont(family=HEAD_FONT, size=10, slant="italic"),
            ).pack(fill="x", padx=10, pady=(0, 6))

            ctk.CTkButton(
                card, text="ANALYZE  →",
                fg_color=PANEL, hover_color=ACCENT, text_color=GOLD,
                height=24, font=ctk.CTkFont(size=10, weight="bold"),
                command=lambda t=p["ticker"]: self._load_ticker(t),
            ).pack(fill="x", padx=10, pady=(0, 8))

    def _build_charts(self, parent):
        self.center_header = ctk.CTkLabel(
            parent, text="—", text_color=TEXT, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=22, weight="bold"),
        )
        self.center_header.pack(fill="x", padx=18, pady=(14, 0))

        self.signal_label = ctk.CTkLabel(
            parent, text="", text_color=MUTED, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=12, slant="italic"),
        )
        self.signal_label.pack(fill="x", padx=18, pady=(2, 4))

        # Multi-horizon expected-value strip (10d / 30d / 60d)
        self.horizons_strip = ctk.CTkFrame(parent, fg_color=BG)
        self.horizons_strip.pack(fill="x", padx=18, pady=(0, 6))

        self.fig_main = _make_figure(figsize=(8, 4.4))
        self.canvas_main = FigureCanvasTkAgg(self.fig_main, master=parent)
        self.canvas_main.get_tk_widget().pack(fill="both", expand=True, padx=12, pady=(0, 8))

        self.fig_ind = _make_figure(figsize=(8, 2.6))
        self.canvas_ind = FigureCanvasTkAgg(self.fig_ind, master=parent)
        self.canvas_ind.get_tk_widget().pack(fill="both", expand=False, padx=12, pady=(0, 12))

    def _build_summary_panel(self, parent):
        ctk.CTkLabel(
            parent, text="DOSSIER", text_color=GOLD, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=13, weight="bold"),
        ).pack(fill="x", padx=14, pady=(14, 6))

        self.summary_scroll = ctk.CTkScrollableFrame(
            parent, fg_color=PANEL,
            scrollbar_button_color=BORDER, scrollbar_button_hover_color=ACCENT,
        )
        self.summary_scroll.pack(fill="both", expand=True, padx=8, pady=(0, 12))

    # ------------ Quant tab actions ------------
    def _on_search(self):
        t = self.search_entry.get().strip().upper()
        if not t:
            return
        self.tabs.set("QUANT DESK")
        self._load_ticker(t)

    def _load_ticker(self, ticker: str):
        self.center_header.configure(text=f"{ticker}   loading…")
        self.signal_label.configure(text="")
        for w in self.summary_scroll.winfo_children():
            w.destroy()
        threading.Thread(target=self._do_load, args=(ticker,), daemon=True).start()

    def _do_load(self, ticker: str):
        try:
            df = get_history(ticker, period="2y", interval="1d")
            spy = get_history("SPY", period="2y", interval="1d")
            if df.empty:
                raise ValueError(f"No data for {ticker}.")
            mc = monte_carlo_gbm(df["Close"], horizon_days=60, n_paths=1500)
            sig = build_signal_report(df)
            summary = write_summary(ticker, df, benchmark_df=spy)
        except Exception as e:
            self.after(0, lambda err=e: self._show_error(ticker, str(err)))
            return
        self.after(0, lambda: self._render_ticker(ticker, df, mc, sig, summary))

    def _show_error(self, ticker, msg):
        self.center_header.configure(text=f"{ticker}   ·   error")
        self.signal_label.configure(text=msg, text_color=RED)

    def _render_ticker(self, ticker, df, mc, sig, summary):
        last = float(df["Close"].iloc[-1])
        prev = float(df["Close"].iloc[-2])
        chg = (last - prev) / prev * 100
        self.center_header.configure(text=f"{ticker}   ${last:,.2f}", text_color=TEXT)
        self.signal_label.configure(
            text=f"{chg:+.2f}% today  ·  {sig.headline}",
            text_color=sig.color,
        )
        self._render_horizons(last, mc, [10, 30, 60])
        self._draw_main_chart(df, mc, ticker)
        self._draw_indicator_chart(df)
        self._render_summary(summary, sig)

    def _render_horizons(self, last_price, mc, days_list):
        """Render a row of expected-value cards for the given horizons."""
        for w in self.horizons_strip.winfo_children():
            w.destroy()
        for d in days_list:
            if d >= mc.paths.shape[1]:
                continue
            paths_d = mc.paths[:, d]
            exp = float(paths_d.mean())
            p_up = float((paths_d > last_price).mean())
            delta = (exp - last_price) / last_price
            delta_color = GREEN if delta >= 0 else RED

            cell = ctk.CTkFrame(
                self.horizons_strip, fg_color=PANEL_2, corner_radius=0,
                border_width=1, border_color=BORDER,
            )
            cell.pack(side="left", expand=True, fill="x", padx=(0, 6))
            ctk.CTkLabel(
                cell, text=f"// {d}D EXPECTED", text_color=ACCENT, anchor="w",
                font=ctk.CTkFont(family=HEAD_FONT, size=10, weight="bold"),
            ).pack(fill="x", padx=10, pady=(6, 0))
            ctk.CTkLabel(
                cell, text=f"${exp:,.2f}", text_color=TEXT, anchor="w",
                font=ctk.CTkFont(family=HEAD_FONT, size=15, weight="bold"),
            ).pack(fill="x", padx=10, pady=(0, 0))
            ctk.CTkLabel(
                cell,
                text=f"{delta*100:+.2f}%   .   P(up) {p_up*100:.0f}%",
                text_color=delta_color, anchor="w",
                font=ctk.CTkFont(family=HEAD_FONT, size=10),
            ).pack(fill="x", padx=10, pady=(0, 6))

    def _draw_main_chart(self, df, mc, ticker):
        self.fig_main.clear()
        ax = self.fig_main.add_subplot(111)
        _apply_noir_axes(ax, title=f"{ticker} · price · bollinger · 60-day GBM projection")
        close = df["Close"]
        idx = close.index
        ax.plot(idx, close, color=TEXT, linewidth=1.2, label="Close")
        ax.plot(idx, sma(close, 20), color=GOLD, linewidth=0.9, alpha=0.9, label="SMA20")
        ax.plot(idx, sma(close, 50), color=ACCENT, linewidth=0.9, alpha=0.9, label="SMA50")
        mid, up, lo = bollinger(close, 20, 2.0)
        ax.fill_between(idx, lo, up, color=GOLD, alpha=0.05)
        ax.plot(idx, up, color=MUTED, linewidth=0.5, linestyle="--", alpha=0.6)
        ax.plot(idx, lo, color=MUTED, linewidth=0.5, linestyle="--", alpha=0.6)

        last_date = idx[-1]
        future_dates = pd.bdate_range(last_date, periods=mc.horizon_days + 1, freq="B")[1:]
        proj_idx = [last_date] + list(future_dates)
        p5 = np.concatenate([[float(close.iloc[-1])], mc.p5[1:]])
        p50 = np.concatenate([[float(close.iloc[-1])], mc.p50[1:]])
        p95 = np.concatenate([[float(close.iloc[-1])], mc.p95[1:]])
        ax.fill_between(proj_idx, p5, p95, color=ACCENT, alpha=0.15, label="MC 5–95%")
        ax.plot(proj_idx, p50, color=ACCENT, linewidth=1.2, linestyle=":", label="MC median")
        for j in range(0, len(mc.paths), max(1, len(mc.paths)//30)):
            ax.plot(proj_idx, [float(close.iloc[-1])] + list(mc.paths[j, 1:]),
                    color=GOLD, alpha=0.04, linewidth=0.5)
        ax.legend(
            loc="upper left", facecolor=PANEL_2, edgecolor=BORDER,
            labelcolor=TEXT, fontsize=8, framealpha=0.95,
        )
        self.fig_main.tight_layout()
        self.canvas_main.draw()

    def _draw_indicator_chart(self, df):
        self.fig_ind.clear()
        gs = self.fig_ind.add_gridspec(1, 2, wspace=0.18)
        close = df["Close"]
        ax1 = self.fig_ind.add_subplot(gs[0, 0])
        _apply_noir_axes(ax1, title="RSI (14)")
        r = rsi(close)
        ax1.plot(close.index, r, color=GOLD, linewidth=1.0)
        ax1.axhline(70, color=RED, linewidth=0.6, linestyle="--", alpha=0.7)
        ax1.axhline(30, color=GREEN, linewidth=0.6, linestyle="--", alpha=0.7)
        ax1.fill_between(close.index, 30, 70, color=GOLD, alpha=0.04)
        ax1.set_ylim(0, 100)

        ax2 = self.fig_ind.add_subplot(gs[0, 1])
        _apply_noir_axes(ax2, title="MACD (12,26,9)")
        macd_line, signal_line, hist = macd(close)
        colors = [GREEN if h >= 0 else RED for h in hist.fillna(0)]
        ax2.bar(close.index, hist.fillna(0), color=colors, width=1.0, alpha=0.5)
        ax2.plot(close.index, macd_line, color=TEXT, linewidth=1.0)
        ax2.plot(close.index, signal_line, color=ACCENT, linewidth=0.9)
        self.fig_ind.tight_layout()
        self.canvas_ind.draw()

    def _render_summary(self, s, sig):
        for w in self.summary_scroll.winfo_children():
            w.destroy()
        ctk.CTkLabel(
            self.summary_scroll, text=s["name"], text_color=TEXT, anchor="w",
            wraplength=380, justify="left",
            font=ctk.CTkFont(family=HEAD_FONT, size=15, weight="bold"),
        ).pack(fill="x", padx=4, pady=(2, 0))
        ctk.CTkLabel(
            self.summary_scroll, text=f"{s['sector']}  ·  {s['industry']}",
            text_color=GOLD, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=10, slant="italic"),
        ).pack(fill="x", padx=4, pady=(0, 8))

        sig_box = ctk.CTkFrame(self.summary_scroll, fg_color=PANEL_2, corner_radius=0)
        sig_box.pack(fill="x", padx=2, pady=(0, 10))
        ctk.CTkLabel(
            sig_box, text=sig.headline, text_color=sig.color, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=13, weight="bold"),
        ).pack(fill="x", padx=10, pady=(8, 4))
        for b in sig.bullets:
            ctk.CTkLabel(
                sig_box, text=f"·  {b}", text_color=TEXT, anchor="w",
                wraplength=370, justify="left", font=ctk.CTkFont(size=11),
            ).pack(fill="x", padx=10, pady=(0, 2))
        ctk.CTkLabel(
            sig_box, text="signals are not instructions — your call",
            text_color=MUTED, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=9, slant="italic"),
        ).pack(fill="x", padx=10, pady=(2, 8))

        ctk.CTkLabel(
            self.summary_scroll, text="WHY IT'S ON THE RADAR",
            text_color=GOLD, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=11, weight="bold"),
        ).pack(fill="x", padx=4, pady=(6, 4))
        for r in s["reasons"]:
            ctk.CTkLabel(
                self.summary_scroll, text=f"·  {r}", text_color=TEXT,
                anchor="w", wraplength=380, justify="left",
                font=ctk.CTkFont(size=11),
            ).pack(fill="x", padx=4, pady=(0, 2))

        ctk.CTkLabel(
            self.summary_scroll, text="ABOUT THE COMPANY",
            text_color=GOLD, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=11, weight="bold"),
        ).pack(fill="x", padx=4, pady=(12, 4))
        ctk.CTkLabel(
            self.summary_scroll, text=s["description"], text_color=TEXT,
            anchor="w", wraplength=380, justify="left",
            font=ctk.CTkFont(family=HEAD_FONT, size=11),
        ).pack(fill="x", padx=4, pady=(0, 6))

        self._kv_block(self.summary_scroll, "FUNDAMENTALS", s["fundamentals"])
        self._kv_block(self.summary_scroll, "QUANT", s["quant"])

        if s["news"]:
            ctk.CTkLabel(
                self.summary_scroll, text="HEADLINES", text_color=GOLD, anchor="w",
                font=ctk.CTkFont(family=HEAD_FONT, size=11, weight="bold"),
            ).pack(fill="x", padx=4, pady=(12, 4))
            for n in s["news"]:
                ctk.CTkLabel(
                    self.summary_scroll, text=f"·  {n['title']}",
                    text_color=TEXT, anchor="w", wraplength=380, justify="left",
                    font=ctk.CTkFont(size=11),
                ).pack(fill="x", padx=4, pady=(0, 1))
                if n.get("publisher"):
                    ctk.CTkLabel(
                        self.summary_scroll, text=f"   {n['publisher']}",
                        text_color=MUTED, anchor="w",
                        font=ctk.CTkFont(family=HEAD_FONT, size=9, slant="italic"),
                    ).pack(fill="x", padx=4, pady=(0, 4))

    def _kv_block(self, parent, title, dct):
        ctk.CTkLabel(
            parent, text=title, text_color=GOLD, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=11, weight="bold"),
        ).pack(fill="x", padx=4, pady=(12, 4))
        box = ctk.CTkFrame(parent, fg_color=PANEL_2, corner_radius=0)
        box.pack(fill="x", padx=2, pady=(0, 4))
        for k, v in dct.items():
            row = ctk.CTkFrame(box, fg_color=PANEL_2)
            row.pack(fill="x", padx=8, pady=2)
            ctk.CTkLabel(
                row, text=k, text_color=MUTED, anchor="w",
                font=ctk.CTkFont(size=11),
            ).pack(side="left")
            ctk.CTkLabel(
                row, text=str(v), text_color=TEXT, anchor="e",
                font=ctk.CTkFont(size=11, weight="bold"),
            ).pack(side="right")


    # ============================ CONTRACT WATCH TAB ============================
    def _build_contracts_tab(self, parent):
        body = ctk.CTkFrame(parent, fg_color=BG, corner_radius=0)
        body.pack(fill="both", expand=True)

        filt = ctk.CTkFrame(body, fg_color=PANEL_2, corner_radius=0, height=58)
        filt.pack(side="top", fill="x")
        filt.pack_propagate(False)

        ctk.CTkLabel(
            filt, text="SECTORS:", text_color=GOLD,
            font=ctk.CTkFont(family=HEAD_FONT, size=11, weight="bold"),
        ).pack(side="left", padx=(16, 8))

        self.var_defense = ctk.BooleanVar(value=True)
        self.var_medical = ctk.BooleanVar(value=True)
        self.var_tech = ctk.BooleanVar(value=True)
        for label, var in [("Defense", self.var_defense), ("Medical", self.var_medical), ("Tech", self.var_tech)]:
            ctk.CTkCheckBox(
                filt, text=label, variable=var,
                fg_color=ACCENT, hover_color="#6a1414",
                border_color=BORDER, text_color=TEXT, checkmark_color=TEXT,
                font=ctk.CTkFont(size=11),
            ).pack(side="left", padx=4)

        ctk.CTkLabel(
            filt, text="MIN $:", text_color=GOLD,
            font=ctk.CTkFont(family=HEAD_FONT, size=11, weight="bold"),
        ).pack(side="left", padx=(16, 4))
        self.min_amount_combo = ctk.CTkOptionMenu(
            filt, values=["$1M", "$5M", "$25M", "$100M"],
            fg_color=PANEL, button_color=ACCENT, button_hover_color="#6a1414",
            text_color=TEXT, width=80,
        )
        self.min_amount_combo.set("$5M")
        self.min_amount_combo.pack(side="left", padx=4)

        ctk.CTkLabel(
            filt, text="WINDOW:", text_color=GOLD,
            font=ctk.CTkFont(family=HEAD_FONT, size=11, weight="bold"),
        ).pack(side="left", padx=(16, 4))
        self.days_combo = ctk.CTkOptionMenu(
            filt, values=["30 days", "90 days", "180 days", "365 days"],
            fg_color=PANEL, button_color=ACCENT, button_hover_color="#6a1414",
            text_color=TEXT, width=100,
        )
        self.days_combo.set("180 days")
        self.days_combo.pack(side="left", padx=4)

        ctk.CTkButton(
            filt, text="REFRESH FEED", fg_color=ACCENT, hover_color="#6a1414",
            text_color=TEXT, command=self._refresh_contracts,
            font=ctk.CTkFont(weight="bold"), width=140,
        ).pack(side="right", padx=16)

        inner = ctk.CTkFrame(body, fg_color=BG, corner_radius=0)
        inner.pack(fill="both", expand=True)

        list_panel = ctk.CTkFrame(inner, fg_color=PANEL, width=440, corner_radius=0)
        list_panel.pack(side="left", fill="y")
        list_panel.pack_propagate(False)

        ctk.CTkLabel(
            list_panel, text="CONTRACT FEED", text_color=GOLD, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=13, weight="bold"),
        ).pack(fill="x", padx=14, pady=(14, 2))
        self.contract_status = ctk.CTkLabel(
            list_panel, text="ready - press Refresh Feed to pull",
            text_color=MUTED, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=10, slant="italic"),
        )
        self.contract_status.pack(fill="x", padx=14, pady=(0, 8))

        self.contract_list = ctk.CTkScrollableFrame(
            list_panel, fg_color=PANEL,
            scrollbar_button_color=BORDER, scrollbar_button_hover_color=ACCENT,
        )
        self.contract_list.pack(fill="both", expand=True, padx=8, pady=(0, 12))

        self.contract_detail = ctk.CTkScrollableFrame(
            inner, fg_color=BG,
            scrollbar_button_color=BORDER, scrollbar_button_hover_color=ACCENT,
        )
        self.contract_detail.pack(side="right", fill="both", expand=True, padx=14, pady=14)

        ctk.CTkLabel(
            self.contract_detail,
            text="Select a contract from the feed for the context analysis.",
            text_color=MUTED, anchor="w", wraplength=700, justify="left",
            font=ctk.CTkFont(family=HEAD_FONT, size=12, slant="italic"),
        ).pack(fill="x", padx=4, pady=10)

    def _refresh_contracts(self):
        sectors = []
        if self.var_defense.get(): sectors.append("defense")
        if self.var_medical.get(): sectors.append("medical")
        if self.var_tech.get(): sectors.append("tech")
        if not sectors:
            self.contract_status.configure(text="select at least one sector")
            return
        amount_map = {"$1M": 1_000_000, "$5M": 5_000_000, "$25M": 25_000_000, "$100M": 100_000_000}
        min_amount = amount_map.get(self.min_amount_combo.get(), 5_000_000)
        days_map = {"30 days": 30, "90 days": 90, "180 days": 180, "365 days": 365}
        days_back = days_map.get(self.days_combo.get(), 180)

        for w in self.contract_list.winfo_children():
            w.destroy()
        self.contract_status.configure(text="querying USAspending.gov...")
        threading.Thread(
            target=self._do_fetch_contracts,
            args=(tuple(sectors), min_amount, days_back),
            daemon=True,
        ).start()

    def _do_fetch_contracts(self, sectors, min_amount, days_back):
        results = fetch_contracts(
            sectors=sectors, min_amount=min_amount, days_back=days_back, page_limit=100,
        )
        enriched = []
        for r in results:
            recipient = r.get("Recipient Name", "") or ""
            ticker = match_ticker(recipient)
            sm = is_small_mid(ticker)
            r["_ticker"] = ticker
            r["_is_small_mid"] = sm
            r["_impact"] = quick_impact_tag(r, ticker, sm)
            enriched.append(r)
        # Sort: HIGH-IMPACT first, then WATCH, then ROUTINE, then NOISE.
        # Within tier, sort by amount.
        enriched.sort(key=lambda x: (
            x["_impact"]["rank"],
            -float(x.get("Award Amount") or 0),
        ))
        self._contract_results = enriched
        self.after(0, self._render_contract_list)

    def _render_contract_list(self):
        for w in self.contract_list.winfo_children():
            w.destroy()
        if not self._contract_results:
            self.contract_status.configure(text="no contracts returned - try wider filters or check connection")
            return
        high = sum(1 for r in self._contract_results if r["_impact"]["tag"] == "HIGH-IMPACT")
        watch = sum(1 for r in self._contract_results if r["_impact"]["tag"] == "WATCH")
        small_mid = sum(1 for r in self._contract_results if r["_is_small_mid"])
        self.contract_status.configure(
            text=f"[ {len(self._contract_results)} awards . {high} HIGH-IMPACT . {watch} WATCH . {small_mid} small-mid ]"
        )
        shown = 0
        for r in self._contract_results:
            if not r["_ticker"] and shown >= 30:
                continue
            self._render_contract_card(r)
            shown += 1

    def _render_contract_card(self, award):
        ticker = award.get("_ticker")
        is_sm = award.get("_is_small_mid")
        impact = award.get("_impact") or {"tag": "NOISE", "color": MUTED}
        amount = float(award.get("Award Amount") or 0)
        recipient = award.get("Recipient Name") or "-"
        agency = award.get("Awarding Agency") or "-"

        # Border color follows the impact tag for at-a-glance scanning
        if impact["tag"] in ("HIGH-IMPACT", "WATCH"):
            border_color = impact["color"]
        elif is_sm:
            border_color = GOLD
        else:
            border_color = BORDER

        card = ctk.CTkFrame(self.contract_list, fg_color=PANEL_2, corner_radius=0,
                            border_width=1, border_color=border_color)
        card.pack(fill="x", padx=4, pady=4)

        # HIGH-IMPACT auto-tag — full-width red bar at the top of the card
        if impact["tag"] == "HIGH-IMPACT":
            tag_strip = ctk.CTkFrame(card, fg_color=ACCENT, height=18, corner_radius=0)
            tag_strip.pack(fill="x", padx=0, pady=0)
            tag_strip.pack_propagate(False)
            ctk.CTkLabel(
                tag_strip, text="// HIGH-IMPACT", text_color="#000000", anchor="w",
                font=ctk.CTkFont(family=HEAD_FONT, size=9, weight="bold"),
            ).pack(side="left", padx=8)

        head = ctk.CTkFrame(card, fg_color=PANEL_2)
        head.pack(fill="x", padx=10, pady=(8, 0))
        ctk.CTkLabel(
            head, text=ticker if ticker else "-", text_color=TEXT, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=14, weight="bold"),
        ).pack(side="left")
        secondary = "SMALL-MID" if is_sm else ("MEGA-CAP" if ticker else "PRIVATE")
        secondary_color = GOLD if is_sm else MUTED
        ctk.CTkLabel(
            head, text=secondary, text_color=secondary_color,
            font=ctk.CTkFont(family=HEAD_FONT, size=9, weight="bold"),
        ).pack(side="left", padx=(8, 0))
        if impact["tag"] == "WATCH":
            ctk.CTkLabel(
                head, text="WATCH", text_color=impact["color"],
                font=ctk.CTkFont(family=HEAD_FONT, size=9, weight="bold"),
            ).pack(side="left", padx=(6, 0))
        ctk.CTkLabel(
            head, text=_fmt_money(amount), text_color=GOLD,
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(side="right")

        recipient_short = recipient if len(recipient) <= 50 else recipient[:48] + "..."
        ctk.CTkLabel(
            card, text=recipient_short, text_color=TEXT, anchor="w",
            wraplength=380, justify="left", font=ctk.CTkFont(size=11),
        ).pack(fill="x", padx=10, pady=(0, 2))

        agency_short = agency if len(agency) <= 50 else agency[:48] + "..."
        ctk.CTkLabel(
            card, text=agency_short, text_color=MUTED, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=10, slant="italic"),
        ).pack(fill="x", padx=10, pady=(0, 6))

        ctk.CTkButton(
            card, text="ANALYZE CONTEXT  ->",
            fg_color=PANEL, hover_color=ACCENT, text_color=GOLD,
            height=24, font=ctk.CTkFont(size=10, weight="bold"),
            command=lambda a=award: self._select_contract(a),
        ).pack(fill="x", padx=10, pady=(0, 8))

    def _select_contract(self, award):
        self._selected_contract = award
        for w in self.contract_detail.winfo_children():
            w.destroy()
        ctk.CTkLabel(
            self.contract_detail, text="loading contextual analysis...",
            text_color=MUTED, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=12, slant="italic"),
        ).pack(fill="x", padx=4, pady=10)
        threading.Thread(target=self._do_score_contract, args=(award,), daemon=True).start()

    def _do_score_contract(self, award):
        ticker = award.get("_ticker")
        info = None
        df = None
        if ticker:
            try:
                info = get_info(ticker)
            except Exception:
                info = None
            try:
                df = get_history(ticker, period="6mo", interval="1d")
            except Exception:
                df = None
        result = score_contract(award, info=info)
        theses = speculative_thesis(award, info=info)
        self.after(0, lambda: self._render_contract_detail(award, info, df, result, theses))

    def _render_contract_detail(self, award, info, df, result, theses=None):
        for w in self.contract_detail.winfo_children():
            w.destroy()

        ticker = award.get("_ticker")
        amount = float(award.get("Award Amount") or 0)
        recipient = award.get("Recipient Name") or "-"
        agency = award.get("Awarding Agency") or "-"
        sub_agency = award.get("Awarding Sub Agency") or ""
        description = award.get("Description") or "(no description provided)"
        award_id = award.get("Award ID") or "-"
        naics = award.get("NAICS") or "-"

        impact = award.get("_impact") or {"tag": "NOISE", "color": MUTED, "reasons": []}

        # If HIGH-IMPACT, full-width red banner above the header
        if impact["tag"] == "HIGH-IMPACT":
            ihb = ctk.CTkFrame(self.contract_detail, fg_color=ACCENT, height=24,
                               corner_radius=0)
            ihb.pack(fill="x", padx=4, pady=(0, 6))
            ihb.pack_propagate(False)
            reasons = ", ".join(impact.get("reasons", [])) or "auto-flagged"
            ctk.CTkLabel(
                ihb,
                text=f"// HIGH-IMPACT  —  potentially material to forward stock price  —  flags: {reasons}",
                text_color="#000000", anchor="w",
                font=ctk.CTkFont(family=HEAD_FONT, size=10, weight="bold"),
            ).pack(side="left", padx=10)

        header_row = ctk.CTkFrame(self.contract_detail, fg_color=BG)
        header_row.pack(fill="x", padx=4, pady=(4, 0))
        ctk.CTkLabel(
            header_row, text=(ticker if ticker else "Unmatched recipient"),
            text_color=TEXT, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=22, weight="bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            header_row, text=f"  .  {_fmt_money(amount)}", text_color=GOLD,
            font=ctk.CTkFont(family=HEAD_FONT, size=18),
        ).pack(side="left")
        # Inline tag pill in header
        tag = impact["tag"]
        if tag in ("HIGH-IMPACT", "WATCH", "ROUTINE"):
            ctk.CTkLabel(
                header_row, text=f"   [ {tag} ]", text_color=impact["color"],
                font=ctk.CTkFont(family=HEAD_FONT, size=11, weight="bold"),
            ).pack(side="left")

        verdict_box = ctk.CTkFrame(self.contract_detail, fg_color=PANEL_2, corner_radius=0)
        verdict_box.pack(fill="x", padx=4, pady=(8, 6))
        verdict_top = ctk.CTkFrame(verdict_box, fg_color=PANEL_2)
        verdict_top.pack(fill="x", padx=12, pady=(10, 4))
        ctk.CTkLabel(
            verdict_top, text=f"CONTEXT  {result['score']}/100  .  {result['verdict']}",
            text_color=result["color"], anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=14, weight="bold"),
        ).pack(side="left")

        bar_bg = ctk.CTkFrame(verdict_box, fg_color=BORDER, height=6, corner_radius=0)
        bar_bg.pack(fill="x", padx=12, pady=(0, 8))
        bar_bg.pack_propagate(False)
        bar_fill = ctk.CTkFrame(
            bar_bg, fg_color=result["color"], corner_radius=0, height=6,
            width=max(1, int(700 * result["score"] / 100)),
        )
        bar_fill.place(x=0, y=0, relheight=1)

        for note in result["notes"]:
            ctk.CTkLabel(
                verdict_box, text=f"·  {note}", text_color=TEXT,
                anchor="w", wraplength=720, justify="left",
                font=ctk.CTkFont(size=11),
            ).pack(fill="x", padx=14, pady=(0, 2))
        ctk.CTkLabel(
            verdict_box,
            text="context score is a heuristic - not a price target. signals, not instructions.",
            text_color=MUTED, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=9, slant="italic"),
        ).pack(fill="x", padx=14, pady=(4, 10))

        self._kv_block_wide(self.contract_detail, "AWARD DETAILS", {
            "Recipient": recipient,
            "Awarding Agency": agency,
            "Sub-Agency": sub_agency or "-",
            "NAICS": str(naics),
            "Period": f"{(award.get('Period of Performance Start Date') or '-')[:10]}  ->  {(award.get('Period of Performance Current End Date') or '-')[:10]}",
            "Award ID": str(award_id),
        })

        ctk.CTkLabel(
            self.contract_detail, text="SCOPE OF WORK", text_color=GOLD, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=11, weight="bold"),
        ).pack(fill="x", padx=4, pady=(12, 4))
        ctk.CTkLabel(
            self.contract_detail, text=description, text_color=TEXT, anchor="w",
            wraplength=760, justify="left", font=ctk.CTkFont(family=HEAD_FONT, size=11),
        ).pack(fill="x", padx=4, pady=(0, 8))

        # ---- SPECULATIVE INVESTMENT THESIS ----
        if theses:
            ctk.CTkLabel(
                self.contract_detail, text="// SPECULATIVE THESIS", text_color=ACCENT,
                anchor="w",
                font=ctk.CTkFont(family=HEAD_FONT, size=12, weight="bold"),
            ).pack(fill="x", padx=4, pady=(14, 4))
            ctk.CTkLabel(
                self.contract_detail,
                text="Why this contract — itself — could move the equity. Pattern observations, not forecasts.",
                text_color=MUTED, anchor="w", wraplength=760, justify="left",
                font=ctk.CTkFont(family=HEAD_FONT, size=10, slant="italic"),
            ).pack(fill="x", padx=4, pady=(0, 6))

            for t in theses:
                tbox = ctk.CTkFrame(self.contract_detail, fg_color=PANEL_2, corner_radius=0,
                                    border_width=1, border_color=BORDER)
                tbox.pack(fill="x", padx=4, pady=4)
                # Title row with red bar
                trow = ctk.CTkFrame(tbox, fg_color=PANEL_2)
                trow.pack(fill="x", padx=10, pady=(8, 2))
                ctk.CTkLabel(
                    trow, text="▎", text_color=ACCENT,
                    font=ctk.CTkFont(family=HEAD_FONT, size=14, weight="bold"),
                ).pack(side="left", padx=(0, 4))
                ctk.CTkLabel(
                    trow, text=t["title"], text_color=TEXT, anchor="w",
                    font=ctk.CTkFont(family=HEAD_FONT, size=12, weight="bold"),
                ).pack(side="left")
                ctk.CTkLabel(
                    tbox, text=t["body"], text_color=TEXT, anchor="w",
                    wraplength=720, justify="left",
                    font=ctk.CTkFont(family=HEAD_FONT, size=11),
                ).pack(fill="x", padx=18, pady=(0, 8))

            # Disclaimer line
            ctk.CTkLabel(
                self.contract_detail,
                text="// theses are reasoning patterns, not predictions. markets can ignore even strong setups.",
                text_color=MUTED, anchor="w",
                font=ctk.CTkFont(family=HEAD_FONT, size=9, slant="italic"),
            ).pack(fill="x", padx=4, pady=(2, 6))

        if ticker and info:
            comp_box = ctk.CTkFrame(self.contract_detail, fg_color=PANEL_2, corner_radius=0)
            comp_box.pack(fill="x", padx=4, pady=(8, 6))
            ctk.CTkLabel(
                comp_box, text=info.get("longName") or info.get("shortName") or ticker,
                text_color=TEXT, anchor="w",
                font=ctk.CTkFont(family=HEAD_FONT, size=14, weight="bold"),
            ).pack(fill="x", padx=12, pady=(10, 0))
            ctk.CTkLabel(
                comp_box, text=f"{info.get('sector') or '-'}  .  {info.get('industry') or '-'}",
                text_color=GOLD, anchor="w",
                font=ctk.CTkFont(family=HEAD_FONT, size=10, slant="italic"),
            ).pack(fill="x", padx=12, pady=(0, 6))

            mc_text = info.get("marketCap")
            rev = info.get("totalRevenue")
            margin = info.get("profitMargins")

            stats_row = ctk.CTkFrame(comp_box, fg_color=PANEL_2)
            stats_row.pack(fill="x", padx=12, pady=(0, 8))

            def _fmt_b(x):
                if not x: return "-"
                if abs(x) >= 1e9: return f"${x/1e9:.2f}B"
                if abs(x) >= 1e6: return f"${x/1e6:.1f}M"
                return f"${x:,.0f}"

            for label, val in [
                ("Market Cap", _fmt_b(mc_text)),
                ("TTM Revenue", _fmt_b(rev)),
                ("Profit Margin", f"{margin*100:.1f}%" if isinstance(margin, (int, float)) else "-"),
                ("Contract / Rev", f"{(amount/rev)*100:.1f}%" if rev else "-"),
            ]:
                cell = ctk.CTkFrame(stats_row, fg_color=PANEL_2)
                cell.pack(side="left", expand=True, fill="x", padx=4)
                ctk.CTkLabel(cell, text=label, text_color=MUTED, anchor="w",
                             font=ctk.CTkFont(family=HEAD_FONT, size=10)).pack(fill="x")
                ctk.CTkLabel(cell, text=val, text_color=TEXT, anchor="w",
                             font=ctk.CTkFont(family=HEAD_FONT, size=12, weight="bold")).pack(fill="x")

            ctk.CTkButton(
                comp_box, text=f"OPEN {ticker} IN QUANT DESK  ->",
                fg_color=ACCENT, hover_color="#6a1414", text_color=TEXT,
                command=lambda t=ticker: self._jump_to_quant(t),
                font=ctk.CTkFont(family=HEAD_FONT, size=11, weight="bold"),
            ).pack(fill="x", padx=12, pady=(0, 10))

        if ticker and df is not None and not df.empty:
            fig = _make_figure(figsize=(8, 2.4))
            ax = fig.add_subplot(111)
            _apply_noir_axes(ax, title=f"{ticker} . 6-month price")
            ax.plot(df.index, df["Close"], color=TEXT, linewidth=1.0)
            ax.fill_between(df.index, df["Close"].min(), df["Close"], color=ACCENT, alpha=0.06)
            fig.tight_layout()
            canvas = FigureCanvasTkAgg(fig, master=self.contract_detail)
            canvas.draw()
            canvas.get_tk_widget().pack(fill="both", expand=False, padx=4, pady=(8, 4))

        if not ticker:
            note = ctk.CTkFrame(self.contract_detail, fg_color=PANEL_2, corner_radius=0,
                                border_width=1, border_color=BORDER)
            note.pack(fill="x", padx=4, pady=(8, 6))
            ctk.CTkLabel(
                note,
                text=(
                    "// recipient not in our publicly traded ticker map. "
                    "may be private, a subsidiary, a non-profit, or a foreign listing. "
                    "contract size is shown but no equity context applies."
                ),
                text_color=MUTED, anchor="w", wraplength=720, justify="left",
                font=ctk.CTkFont(family=HEAD_FONT, size=11, slant="italic"),
            ).pack(fill="x", padx=12, pady=10)

    def _kv_block_wide(self, parent, title, dct):
        ctk.CTkLabel(
            parent, text=title, text_color=ACCENT, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=11, weight="bold"),
        ).pack(fill="x", padx=4, pady=(12, 4))
        box = ctk.CTkFrame(parent, fg_color=PANEL_2, corner_radius=0,
                           border_width=1, border_color=BORDER)
        box.pack(fill="x", padx=2, pady=(0, 4))
        for k, v in dct.items():
            row = ctk.CTkFrame(box, fg_color=PANEL_2)
            row.pack(fill="x", padx=12, pady=3)
            ctk.CTkLabel(
                row, text=k, text_color=MUTED, anchor="w", width=160,
                font=ctk.CTkFont(family=HEAD_FONT, size=11),
            ).pack(side="left")
            ctk.CTkLabel(
                row, text=str(v), text_color=TEXT, anchor="w", wraplength=540,
                justify="left", font=ctk.CTkFont(family=HEAD_FONT, size=11),
            ).pack(side="left", fill="x", expand=True)

    def _jump_to_quant(self, ticker):
        self.tabs.set("QUANT DESK")
        self._load_ticker(ticker)

    # ============================ RISK-ON TAB ============================
    def _build_risk_tab(self, parent):
        body = ctk.CTkFrame(parent, fg_color=BG, corner_radius=0)
        body.pack(fill="both", expand=True)

        # Risk warning banner — large, red, unmissable
        banner = ctk.CTkFrame(body, fg_color="#1a0000", corner_radius=0,
                              border_width=1, border_color=ACCENT, height=58)
        banner.pack(side="top", fill="x")
        banner.pack_propagate(False)
        warn_row = ctk.CTkFrame(banner, fg_color="#1a0000")
        warn_row.pack(fill="both", expand=True, padx=14, pady=8)
        ctk.CTkLabel(
            warn_row, text="// HIGH-RISK / SHORT-TERM SPECULATION ZONE",
            text_color=ACCENT, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=14, weight="bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            warn_row,
            text="  positions can lose 50%+ in days  .  sized for adverse scenarios  .  not investment advice",
            text_color=TEXT, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=10, slant="italic"),
        ).pack(side="left")

        # Filter / refresh strip
        filt = ctk.CTkFrame(body, fg_color=PANEL_2, corner_radius=0, height=44)
        filt.pack(side="top", fill="x")
        filt.pack_propagate(False)
        ctk.CTkLabel(
            filt, text="// SORT:", text_color=ACCENT,
            font=ctk.CTkFont(family=HEAD_FONT, size=11, weight="bold"),
        ).pack(side="left", padx=(16, 6))
        self.risk_sort = ctk.CTkOptionMenu(
            filt,
            values=["Risk Score", "Volatility", "5d Return", "Beta", "Drawdown", "RSI"],
            fg_color=PANEL, button_color=ACCENT, button_hover_color="#6a1414",
            text_color=TEXT, width=140,
            command=lambda _v: self._render_risk_list(),
        )
        self.risk_sort.set("Risk Score")
        self.risk_sort.pack(side="left", padx=4)

        ctk.CTkButton(
            filt, text="REFRESH FEED", fg_color=ACCENT, hover_color="#6a1414",
            text_color=TEXT, command=self._refresh_risk,
            font=ctk.CTkFont(family=HEAD_FONT, weight="bold"), width=140,
        ).pack(side="right", padx=16)

        inner = ctk.CTkFrame(body, fg_color=BG, corner_radius=0)
        inner.pack(fill="both", expand=True)

        # Left: ranked risk-on list
        list_panel = ctk.CTkFrame(inner, fg_color=PANEL, width=380, corner_radius=0)
        list_panel.pack(side="left", fill="y")
        list_panel.pack_propagate(False)

        ctk.CTkLabel(
            list_panel, text="// HIGH-VOL UNIVERSE", text_color=ACCENT, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=13, weight="bold"),
        ).pack(fill="x", padx=14, pady=(14, 2))
        self.risk_status = ctk.CTkLabel(
            list_panel, text="[ idle - press REFRESH FEED ]", text_color=MUTED, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=10, slant="italic"),
        )
        self.risk_status.pack(fill="x", padx=14, pady=(0, 8))

        self.risk_list = ctk.CTkScrollableFrame(
            list_panel, fg_color=PANEL,
            scrollbar_button_color=BORDER, scrollbar_button_hover_color=ACCENT,
        )
        self.risk_list.pack(fill="both", expand=True, padx=8, pady=(0, 12))

        # Right: detail + thesis
        self.risk_detail = ctk.CTkScrollableFrame(
            inner, fg_color=BG,
            scrollbar_button_color=BORDER, scrollbar_button_hover_color=ACCENT,
        )
        self.risk_detail.pack(side="right", fill="both", expand=True, padx=14, pady=14)

        ctk.CTkLabel(
            self.risk_detail,
            text="// select a name from the universe for short-term thesis + risk read",
            text_color=MUTED, anchor="w", wraplength=700, justify="left",
            font=ctk.CTkFont(family=HEAD_FONT, size=12, slant="italic"),
        ).pack(fill="x", padx=4, pady=10)

        self._risk_rows = []

    def _refresh_risk(self):
        self.risk_status.configure(text="[ screening high-vol universe... ]")
        for w in self.risk_list.winfo_children():
            w.destroy()
        threading.Thread(target=self._do_screen_risk, daemon=True).start()

    def _do_screen_risk(self):
        try:
            rows = screen_risk_universe()
        except Exception as e:
            print("risk screen error:", e)
            rows = []
        self._risk_rows = rows
        self.after(0, self._render_risk_list)

    def _render_risk_list(self):
        for w in self.risk_list.winfo_children():
            w.destroy()
        if not self._risk_rows:
            self.risk_status.configure(text="[ no data - check connection ]")
            return

        sort_field = self.risk_sort.get() if hasattr(self, "risk_sort") else "Risk Score"
        keymap = {
            "Risk Score": lambda r: -r["risk_score"],
            "Volatility": lambda r: -r["ann_vol"],
            "5d Return": lambda r: -r["ret_5"],
            "Beta": lambda r: -(r["beta"] if r["beta"] == r["beta"] else 0),
            "Drawdown": lambda r: r["max_dd"],
            "RSI": lambda r: -r["rsi"],
        }
        rows = sorted(self._risk_rows, key=keymap.get(sort_field, keymap["Risk Score"]))
        self.risk_status.configure(text=f"[ {len(rows)} names . sorted by {sort_field} ]")

        for r in rows:
            self._render_risk_card(r)

    def _render_risk_card(self, row):
        score = row["risk_score"]
        if score >= 80:
            tier_color = ACCENT
            tier_text = "EXTREME"
        elif score >= 60:
            tier_color = GOLD
            tier_text = "HIGH"
        elif score >= 40:
            tier_color = "#c9a227"
            tier_text = "ELEVATED"
        else:
            tier_color = MUTED
            tier_text = "MODERATE"

        card = ctk.CTkFrame(self.risk_list, fg_color=PANEL_2, corner_radius=0,
                            border_width=1, border_color=tier_color)
        card.pack(fill="x", padx=4, pady=4)

        head = ctk.CTkFrame(card, fg_color=PANEL_2)
        head.pack(fill="x", padx=10, pady=(8, 0))
        ctk.CTkLabel(
            head, text=row["ticker"], text_color=TEXT, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=15, weight="bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            head, text=f"  {tier_text}", text_color=tier_color,
            font=ctk.CTkFont(family=HEAD_FONT, size=10, weight="bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            head, text=f"R {score}", text_color=tier_color,
            font=ctk.CTkFont(family=HEAD_FONT, size=12, weight="bold"),
        ).pack(side="right")

        ret_color = GREEN if row["ret_5"] >= 0 else RED
        ctk.CTkLabel(
            card,
            text=f"${row['last']:,.2f}  .  5d {row['ret_5']*100:+.1f}%  .  vol {row['ann_vol']*100:.0f}%",
            text_color=ret_color, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=11),
        ).pack(fill="x", padx=10, pady=(0, 2))

        beta_str = f"{row['beta']:.2f}" if row["beta"] == row["beta"] else "-"
        ctk.CTkLabel(
            card,
            text=f"beta {beta_str}  .  dd {row['max_dd']*100:.0f}%  .  rsi {row['rsi']:.0f}",
            text_color=MUTED, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=10, slant="italic"),
        ).pack(fill="x", padx=10, pady=(0, 6))

        ctk.CTkButton(
            card, text="ANALYZE  ->",
            fg_color=PANEL, hover_color=ACCENT, text_color=GOLD,
            height=24, font=ctk.CTkFont(family=HEAD_FONT, size=10, weight="bold"),
            command=lambda r=row: self._select_risk(r),
        ).pack(fill="x", padx=10, pady=(0, 8))

    def _select_risk(self, row):
        for w in self.risk_detail.winfo_children():
            w.destroy()
        ctk.CTkLabel(
            self.risk_detail, text="[ loading short-term thesis... ]",
            text_color=MUTED, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=12, slant="italic"),
        ).pack(fill="x", padx=4, pady=10)
        threading.Thread(target=self._do_render_risk, args=(row,), daemon=True).start()

    def _do_render_risk(self, row):
        ticker = row["ticker"]
        info = None
        df = None
        mc = None
        try:
            info = get_info(ticker)
        except Exception:
            info = None
        try:
            df = get_history(ticker, period="6mo", interval="1d")
        except Exception:
            df = None
        if df is not None and not df.empty and len(df) >= 30:
            try:
                # Short-horizon Monte Carlo for the speculative read
                mc = monte_carlo_gbm(df["Close"], horizon_days=14, n_paths=2000)
            except Exception:
                mc = None
        thesis = short_term_thesis(row)
        self.after(0, lambda: self._render_risk_detail(row, info, df, thesis, mc))

    def _render_risk_detail(self, row, info, df, thesis, mc=None):
        for w in self.risk_detail.winfo_children():
            w.destroy()

        ticker = row["ticker"]
        score = row["risk_score"]
        name = info.get("longName") if info else ticker

        # Header
        header = ctk.CTkFrame(self.risk_detail, fg_color=BG)
        header.pack(fill="x", padx=4, pady=(4, 0))
        ctk.CTkLabel(
            header, text="▎", text_color=ACCENT,
            font=ctk.CTkFont(family=HEAD_FONT, size=24, weight="bold"),
        ).pack(side="left", padx=(0, 4))
        ctk.CTkLabel(
            header, text=ticker, text_color=TEXT, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=22, weight="bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            header, text=f"  ${row['last']:,.2f}", text_color=GOLD,
            font=ctk.CTkFont(family=HEAD_FONT, size=18),
        ).pack(side="left")

        if name and name != ticker:
            ctk.CTkLabel(
                self.risk_detail, text=name, text_color=MUTED, anchor="w",
                font=ctk.CTkFont(family=HEAD_FONT, size=11, slant="italic"),
            ).pack(fill="x", padx=4, pady=(0, 6))

        # Risk score banner
        risk_box = ctk.CTkFrame(self.risk_detail, fg_color="#180000", corner_radius=0,
                                border_width=1, border_color=ACCENT)
        risk_box.pack(fill="x", padx=4, pady=(8, 6))
        rtop = ctk.CTkFrame(risk_box, fg_color="#180000")
        rtop.pack(fill="x", padx=12, pady=(10, 4))
        ctk.CTkLabel(
            rtop, text=f"// RISK SCORE  {score}/100", text_color=ACCENT, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=14, weight="bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            rtop, text=f"  setup: {thesis['setup']}", text_color=GOLD,
            font=ctk.CTkFont(family=HEAD_FONT, size=12),
        ).pack(side="left")

        # Risk score bar
        bar_bg = ctk.CTkFrame(risk_box, fg_color=BORDER, height=4, corner_radius=0)
        bar_bg.pack(fill="x", padx=12, pady=(0, 8))
        bar_bg.pack_propagate(False)
        ctk.CTkFrame(
            bar_bg, fg_color=ACCENT, corner_radius=0,
            width=max(1, int(700 * score / 100)), height=4,
        ).place(x=0, y=0, relheight=1)

        # Hard warning line
        ctk.CTkLabel(
            risk_box, text=thesis["warning"], text_color=ACCENT, anchor="w",
            wraplength=720, justify="left",
            font=ctk.CTkFont(family=HEAD_FONT, size=11, weight="bold"),
        ).pack(fill="x", padx=14, pady=(0, 10))

        # Short-horizon expected-value strip (3/6/9/14 day)
        if mc is not None:
            ctk.CTkLabel(
                self.risk_detail,
                text="// SHORT-HORIZON EXPECTED VALUE  (gbm monte carlo, 2000 paths)",
                text_color=ACCENT, anchor="w",
                font=ctk.CTkFont(family=HEAD_FONT, size=11, weight="bold"),
            ).pack(fill="x", padx=4, pady=(12, 4))

            strip = ctk.CTkFrame(self.risk_detail, fg_color=BG)
            strip.pack(fill="x", padx=2, pady=(0, 4))
            last_price = row["last"]
            for d in [3, 6, 9, 14]:
                if d >= mc.paths.shape[1]:
                    continue
                paths_d = mc.paths[:, d]
                exp = float(paths_d.mean())
                p_up = float((paths_d > last_price).mean())
                p5 = float(np.percentile(paths_d, 5))
                p95 = float(np.percentile(paths_d, 95))
                delta = (exp - last_price) / last_price
                delta_color = GREEN if delta >= 0 else RED

                cell = ctk.CTkFrame(
                    strip, fg_color=PANEL_2, corner_radius=0,
                    border_width=1, border_color=BORDER,
                )
                cell.pack(side="left", expand=True, fill="x", padx=(0, 6))
                ctk.CTkLabel(
                    cell, text=f"// {d}D", text_color=ACCENT, anchor="w",
                    font=ctk.CTkFont(family=HEAD_FONT, size=10, weight="bold"),
                ).pack(fill="x", padx=10, pady=(6, 0))
                ctk.CTkLabel(
                    cell, text=f"${exp:,.2f}", text_color=TEXT, anchor="w",
                    font=ctk.CTkFont(family=HEAD_FONT, size=14, weight="bold"),
                ).pack(fill="x", padx=10, pady=(0, 0))
                ctk.CTkLabel(
                    cell, text=f"{delta*100:+.2f}%   p(up) {p_up*100:.0f}%",
                    text_color=delta_color, anchor="w",
                    font=ctk.CTkFont(family=HEAD_FONT, size=10),
                ).pack(fill="x", padx=10, pady=(0, 0))
                ctk.CTkLabel(
                    cell, text=f"5-95: {p5:.2f} - {p95:.2f}",
                    text_color=MUTED, anchor="w",
                    font=ctk.CTkFont(family=HEAD_FONT, size=9, slant="italic"),
                ).pack(fill="x", padx=10, pady=(0, 6))

            ctk.CTkLabel(
                self.risk_detail,
                text="// short-horizon GBM has no edge predicting direction - read these as a *plausibility band*. high vol = wide bands.",
                text_color=MUTED, anchor="w", wraplength=720, justify="left",
                font=ctk.CTkFont(family=HEAD_FONT, size=9, slant="italic"),
            ).pack(fill="x", padx=4, pady=(2, 6))

        # Metrics grid
        ctk.CTkLabel(
            self.risk_detail, text="// RISK METRICS", text_color=ACCENT, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=11, weight="bold"),
        ).pack(fill="x", padx=4, pady=(12, 4))
        m_box = ctk.CTkFrame(self.risk_detail, fg_color=PANEL_2, corner_radius=0,
                             border_width=1, border_color=BORDER)
        m_box.pack(fill="x", padx=2, pady=(0, 6))
        m_row = ctk.CTkFrame(m_box, fg_color=PANEL_2)
        m_row.pack(fill="x", padx=12, pady=10)

        beta_str = f"{row['beta']:.2f}" if row["beta"] == row["beta"] else "-"
        for label, val, val_color in [
            ("Ann. Vol", f"{row['ann_vol']*100:.0f}%", ACCENT if row["ann_vol"] > 0.6 else TEXT),
            ("Max DD 12mo", f"{row['max_dd']*100:.0f}%", ACCENT if row["max_dd"] < -0.4 else TEXT),
            ("Beta v SPY", beta_str, ACCENT if (row["beta"] == row["beta"] and row["beta"] > 1.5) else TEXT),
            ("30d Swing", f"{row['swing_30d']*100:.0f}%", ACCENT if row["swing_30d"] > 0.3 else TEXT),
            ("RSI(14)", f"{row['rsi']:.0f}", ACCENT if row["rsi"] > 70 or row["rsi"] < 30 else TEXT),
            ("5d Return", f"{row['ret_5']*100:+.1f}%", GREEN if row["ret_5"] >= 0 else RED),
        ]:
            cell = ctk.CTkFrame(m_row, fg_color=PANEL_2)
            cell.pack(side="left", expand=True, fill="x", padx=4)
            ctk.CTkLabel(cell, text=label, text_color=MUTED, anchor="w",
                         font=ctk.CTkFont(family=HEAD_FONT, size=10)).pack(fill="x")
            ctk.CTkLabel(cell, text=val, text_color=val_color, anchor="w",
                         font=ctk.CTkFont(family=HEAD_FONT, size=13, weight="bold")).pack(fill="x")

        # Short-term setup notes
        ctk.CTkLabel(
            self.risk_detail, text="// SHORT-TERM SETUP NOTES", text_color=ACCENT, anchor="w",
            font=ctk.CTkFont(family=HEAD_FONT, size=11, weight="bold"),
        ).pack(fill="x", padx=4, pady=(14, 4))
        ctk.CTkLabel(
            self.risk_detail,
            text="pattern observations only. these are what short-term traders watch - not predictions.",
            text_color=MUTED, anchor="w", wraplength=720, justify="left",
            font=ctk.CTkFont(family=HEAD_FONT, size=10, slant="italic"),
        ).pack(fill="x", padx=4, pady=(0, 4))
        for n in thesis["notes"]:
            line = ctk.CTkFrame(self.risk_detail, fg_color=BG)
            line.pack(fill="x", padx=4, pady=2)
            ctk.CTkLabel(
                line, text="▎", text_color=ACCENT,
                font=ctk.CTkFont(family=HEAD_FONT, size=12),
            ).pack(side="left", padx=(0, 4))
            ctk.CTkLabel(
                line, text=n, text_color=TEXT, anchor="w",
                wraplength=720, justify="left",
                font=ctk.CTkFont(family=HEAD_FONT, size=11),
            ).pack(side="left", fill="x", expand=True)

        # Mini chart
        if df is not None and not df.empty:
            fig = _make_figure(figsize=(8, 2.6))
            ax = fig.add_subplot(111)
            _apply_noir_axes(ax, title=f"{ticker} . 6-month price (sma20)")
            ax.plot(df.index, df["Close"], color=TEXT, linewidth=1.0)
            ax.plot(df.index, sma(df["Close"], 20), color=ACCENT, linewidth=0.8, alpha=0.9)
            ax.fill_between(df.index, df["Close"].min(), df["Close"], color=ACCENT, alpha=0.06)
            fig.tight_layout()
            canvas = FigureCanvasTkAgg(fig, master=self.risk_detail)
            canvas.draw()
            canvas.get_tk_widget().pack(fill="both", expand=False, padx=4, pady=(10, 4))

        # Open in Quant Desk
        ctk.CTkButton(
            self.risk_detail, text=f"OPEN {ticker} IN QUANT DESK  ->",
            fg_color=ACCENT, hover_color="#6a1414", text_color=TEXT,
            command=lambda t=ticker: self._jump_to_quant(t),
            font=ctk.CTkFont(family=HEAD_FONT, size=11, weight="bold"),
        ).pack(fill="x", padx=4, pady=(8, 4))


def main():
    EdgefallIndexApp().mainloop()


if __name__ == "__main__":
    main()
