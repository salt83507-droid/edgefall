"""
USAspending.gov contract intelligence.

Pulls recent federal contract awards filtered by NAICS sector (defense /
medical / tech), matches recipients against a curated list of publicly
traded small-to-mid-cap tickers, and scores each contract by *context*
(materiality vs revenue, strategic customer, contract horizon, narrative
themes) rather than headline dollar value.

Public USAspending API — no key required.
Endpoint: https://api.usaspending.gov/api/v2/search/spending_by_award/
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Optional

import requests


CACHE_DIR = Path.home() / ".noir_stocks_cache"
CACHE_DIR.mkdir(exist_ok=True)

API_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"


# NAICS classification — sector buckets the user cares about.
NAICS = {
    "defense": [
        "336411",  # Aircraft Manufacturing
        "336414",  # Guided Missile and Space Vehicle Manufacturing
        "336992",  # Military Armored Vehicle / Tank Components
        "541330",  # Engineering Services
        "541715",  # R&D in Physical/Engineering/Life Sciences
        "334511",  # Search/Detection/Navigation Instruments
        "517410",  # Satellite Telecommunications
        "928110",  # National Security
    ],
    "medical": [
        "325412",  # Pharmaceutical Preparation Mfg
        "325414",  # Biological Product Mfg
        "339112",  # Surgical and Medical Instrument Mfg
        "339113",  # Surgical Appliance and Supplies Mfg
        "541714",  # R&D in Biotechnology
        "621511",  # Medical Laboratories
        "541715",  # R&D incl. life sciences
    ],
    "tech": [
        "511210",  # Software Publishers
        "541511",  # Custom Computer Programming
        "541512",  # Computer Systems Design
        "518210",  # Data Processing / Hosting / Cloud
        "334111",  # Electronic Computer Manufacturing
        "541519",  # Other Computer-Related Services
    ],
}


# Recipient name → ticker. USAspending recipient strings are messy
# ("PALANTIR USG, INC.", "PALANTIR TECHNOLOGIES INC."), so we use case-
# insensitive substring matching on canonical fragments.
RECIPIENT_TO_TICKER: dict[str, str] = {
    # --- Defense / aerospace small & mid ---
    "KRATOS": "KTOS",
    "AEROVIRONMENT": "AVAV",
    "MERCURY SYSTEMS": "MRCY",
    "CURTISS-WRIGHT": "CW",
    "CURTISS WRIGHT": "CW",
    "HEICO": "HEI",
    "TRANSDIGM": "TDG",
    "TEXTRON": "TXT",
    "HUNTINGTON INGALLS": "HII",
    "L3HARRIS": "LHX",
    "L-3 HARRIS": "LHX",
    "L3 HARRIS": "LHX",
    "PARSONS": "PSN",
    "VECTRUS": "VVX",
    "V2X": "VVX",
    "ELBIT": "ESLT",
    # Defense services / IT
    "LEIDOS": "LDOS",
    "CACI": "CACI",
    "BOOZ ALLEN": "BAH",
    "SCIENCE APPLICATIONS INTERNATIONAL": "SAIC",
    "MAXIMUS": "MMS",
    "MANTECH": "MANT",
    "PERSPECTA": "PRSP",
    # Space / satellite small caps
    "PLANET LABS": "PL",
    "BLACKSKY": "BKSY",
    "ROCKET LAB": "RKLB",
    "SPIRE GLOBAL": "SPIR",
    "VIRGIN GALACTIC": "SPCE",
    "INTUITIVE MACHINES": "LUNR",
    # Drones / autonomy
    "RED CAT": "RCAT",
    "ONDAS": "ONDS",
    "EHANG": "EH",
    "JOBY": "JOBY",
    "ARCHER AVIATION": "ACHR",
    # AI / data / cyber
    "PALANTIR": "PLTR",
    "BIGBEAR.AI": "BBAI",
    "BIGBEAR AI": "BBAI",
    "C3.AI": "AI",
    "C3 AI": "AI",
    "IONQ": "IONQ",
    "RIGETTI": "RGTI",
    "D-WAVE": "QBTS",
    "DWAVE": "QBTS",
    "NUTANIX": "NTNX",
    "VARONIS": "VRNS",
    "TENABLE": "TENB",
    "RAPID7": "RPD",
    "SNOWFLAKE": "SNOW",
    "DATADOG": "DDOG",
    "CLOUDFLARE": "NET",
    "CROWDSTRIKE": "CRWD",
    "SUMO LOGIC": "SUMO",
    "JFROG": "FROG",
    "DOMO": "DOMO",
    "VEEVA": "VEEV",
    # --- Medical small & mid ---
    "MODERNA": "MRNA",
    "BIONTECH": "BNTX",
    "REGENERON": "REGN",
    "VERTEX": "VRTX",
    "ICU MEDICAL": "ICUI",
    "HOLOGIC": "HOLX",
    "INSULET": "PODD",
    "TELEFLEX": "TFX",
    "MASIMO": "MASI",
    "PENUMBRA": "PEN",
    "IRHYTHM": "IRTC",
    "INVITAE": "NVTA",
    "EXACT SCIENCES": "EXAS",
    "NATERA": "NTRA",
    "GUARDANT": "GH",
    "10X GENOMICS": "TXG",
    "TWIST BIOSCIENCE": "TWST",
    "EMERGENT BIOSOLUTIONS": "EBS",
    "DYNAVAX": "DVAX",
    "OVID": "OVID",
    "ANIXA": "ANIX",
    # Defense large-cap (we still flag if they show up so the user can compare)
    "LOCKHEED MARTIN": "LMT",
    "RAYTHEON": "RTX",
    "RTX CORP": "RTX",
    "NORTHROP GRUMMAN": "NOC",
    "GENERAL DYNAMICS": "GD",
    "BOEING": "BA",
}


# Approximate market cap tiers — used to flag what counts as "small to mid".
# We'll filter the list shown to the user using this.
SIZE_TIER = {
    # Small-mid (under ~$15B). These are the ones the user wants to highlight.
    "KTOS","AVAV","MRCY","CW","PSN","VVX","BKSY","PL","RKLB","SPIR","SPCE","LUNR",
    "RCAT","ONDS","BBAI","AI","IONQ","RGTI","QBTS","VRNS","TENB","RPD","SUMO",
    "FROG","DOMO","ICUI","PODD","MASI","PEN","IRTC","NTRA","TXG","TWST","EBS",
    "DVAX","OVID","ANIX","NVTA","GH","EXAS","BNTX","SAIC","MANT","MMS","BAH",
    "CACI","HII","TXT","ESLT","JOBY","ACHR","EH","NTNX","HEI","HOLX","TFX",
}
# Mega-caps included only so the user can compare scale; we grey them out in the UI.
MEGA_CAPS = {"PLTR","SNOW","CRWD","DDOG","NET","VEEV","LMT","RTX","NOC","GD","BA","TDG","LHX","REGN","VRTX","MRNA","LDOS"}


def match_ticker(recipient_name: str) -> Optional[str]:
    if not recipient_name:
        return None
    upper = recipient_name.upper()
    # Match longer keys first to avoid e.g. "BIONTECH" matching before "BOEING"
    for needle in sorted(RECIPIENT_TO_TICKER.keys(), key=len, reverse=True):
        if needle in upper:
            return RECIPIENT_TO_TICKER[needle]
    return None


def is_small_mid(ticker: Optional[str]) -> bool:
    return bool(ticker) and ticker in SIZE_TIER


# ---------------------- API client ----------------------

def _cache_path(sectors, min_amount, max_amount, days_back) -> Path:
    key = f"contracts_{dt.date.today().isoformat()}_{'_'.join(sorted(sectors))}_{min_amount}_{max_amount}_{days_back}"
    return CACHE_DIR / f"{key}.json"


def fetch_contracts(
    sectors: tuple = ("defense", "medical", "tech"),
    min_amount: int = 5_000_000,
    max_amount: int = 750_000_000,
    days_back: int = 180,
    page_limit: int = 100,
) -> list[dict]:
    """Fetch recent procurement contracts. Cached per-day on disk."""
    path = _cache_path(sectors, min_amount, max_amount, days_back)
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass

    end = dt.date.today()
    start = end - dt.timedelta(days=days_back)

    naics: list[str] = []
    for s in sectors:
        for code in NAICS.get(s, []):
            if code not in naics:
                naics.append(code)

    body = {
        "filters": {
            "award_type_codes": ["A", "B", "C", "D"],  # Procurement contracts
            "time_period": [{"start_date": start.isoformat(), "end_date": end.isoformat()}],
            "award_amounts": [{"lower_bound": min_amount, "upper_bound": max_amount}],
            "naics_codes": naics,
        },
        "fields": [
            "Award ID", "Recipient Name", "Award Amount", "Awarding Agency",
            "Awarding Sub Agency", "Award Type", "NAICS", "Description",
            "Period of Performance Start Date", "Period of Performance Current End Date",
            "recipient_id",
        ],
        "page": 1,
        "limit": page_limit,
        "sort": "Award Amount",
        "order": "desc",
    }

    try:
        r = requests.post(API_URL, json=body, timeout=30)
        r.raise_for_status()
        results = r.json().get("results", [])
    except Exception as e:
        print(f"[contracts] USAspending fetch failed: {e}")
        results = []

    if results:
        try:
            with open(path, "w") as f:
                json.dump(results, f)
        except Exception:
            pass

    return results


# ---------------------- Context scoring ----------------------

def score_contract(award: dict, info: Optional[dict] = None) -> dict:
    """
    Compute a 0-100 'context score' weighted by:
      - Materiality (contract / trailing revenue) — primary driver
      - Strategic agency (DARPA, Space Force, NIH, BARDA score higher than GSA)
      - Multi-year period of performance (recurring-revenue proxy)
      - Description keywords linked to high-narrative themes (AI, hypersonic, vaccine)

    Returns {score, verdict, color, notes[]}.
    """
    amount = float(award.get("Award Amount") or 0)
    agency = (award.get("Awarding Agency") or "").upper()
    sub_agency = (award.get("Awarding Sub Agency") or "").upper()
    description = (award.get("Description") or "").upper()

    score = 0
    notes: list[str] = []

    # --- Materiality vs revenue ---
    if info:
        rev = info.get("totalRevenue")
        if rev and rev > 0:
            ratio = amount / rev
            if ratio > 0.50:
                score += 45
                notes.append(f"Transformative — contract equals {ratio*100:.0f}% of trailing revenue.")
            elif ratio > 0.25:
                score += 35
                notes.append(f"Highly material — {ratio*100:.0f}% of trailing revenue.")
            elif ratio > 0.10:
                score += 22
                notes.append(f"Material — {ratio*100:.0f}% of trailing revenue.")
            elif ratio > 0.02:
                score += 10
                notes.append(f"Meaningful — {ratio*100:.1f}% of trailing revenue.")
            else:
                notes.append(f"Modest — only {ratio*100:.2f}% of trailing revenue (low single-deal impact).")
        else:
            score += 12
            notes.append("Revenue unknown — flagged on contract size alone.")
    else:
        # No company info — fall back to raw size brackets
        if amount > 100_000_000:
            score += 22
            notes.append(f"Large dollar value (${amount/1e6:.0f}M).")
        elif amount > 25_000_000:
            score += 14
            notes.append(f"Significant dollar value (${amount/1e6:.0f}M).")
        else:
            score += 6

    # --- Strategic agency tiering ---
    strategic = [
        ("DARPA", 22, "DARPA — explicit cutting-edge R&D customer."),
        ("SPACE FORCE", 18, "Space Force — high-priority growth customer."),
        ("INTELLIGENCE", 18, "IC customer — classified scope often signals follow-on potential."),
        ("BARDA", 18, "BARDA — biodefense / pandemic prep, multi-year stockpile potential."),
        ("NASA", 16, "NASA — high-profile, often headline-driving."),
        ("NATIONAL INSTITUTES OF HEALTH", 14, "NIH — directly tied to clinical pipelines."),
        ("AIR FORCE", 12, "Air Force — strategic platform programs."),
        ("NAVY", 12, "Navy — multi-year platform funding."),
        ("ARMY", 11, "Army — recurring program structure."),
        ("DEPT OF DEFENSE", 10, "DoD prime customer."),
        ("DEPARTMENT OF DEFENSE", 10, "DoD prime customer."),
        ("ENERGY", 8, "DOE — national-lab adjacent contracts can have multipliers."),
    ]
    for kw, pts, note in strategic:
        if kw in agency or kw in sub_agency:
            score += pts
            notes.append(note)
            break

    # --- Period of performance ---
    try:
        s = dt.datetime.fromisoformat(
            (award.get("Period of Performance Start Date") or "").split("T")[0]
        )
        e = dt.datetime.fromisoformat(
            (award.get("Period of Performance Current End Date") or "").split("T")[0]
        )
        years = (e - s).days / 365.25
        if years >= 5:
            score += 14
            notes.append(f"Multi-year horizon ({years:.1f}y) — durable revenue tail.")
        elif years >= 2:
            score += 8
            notes.append(f"Multi-year horizon ({years:.1f}y).")
        elif years >= 1:
            score += 3
    except Exception:
        pass

    # --- Description keyword themes ---
    themes = [
        ("HYPERSONIC", 12, "hypersonic — top-tier defense narrative theme."),
        ("ARTIFICIAL INTELLIGENCE", 10, "AI explicit in scope — narrative tailwind."),
        ("MACHINE LEARNING", 8, "ML in scope of work."),
        (" AI ", 8, "AI scope reference."),
        ("AUTONOMOUS", 8, "autonomy theme — premium-multiple narrative."),
        ("UNMANNED", 7, "unmanned systems — drone narrative."),
        ("QUANTUM", 10, "quantum — emerging high-narrative theme."),
        ("CYBER", 7, "cyber — recurring spend category."),
        ("SATELLITE", 7, "satellite — space-segment growth narrative."),
        ("LAUNCH", 6, "launch services — space narrative."),
        ("VACCINE", 9, "vaccine scope — biodefense / pandemic prep."),
        ("ONCOLOGY", 7, "oncology pipeline reference."),
        ("CLINICAL TRIAL", 6, "clinical trial — pipeline progression."),
        ("PRODUCTION", 7, "production phase — past R&D, into recurring revenue."),
        ("FULL RATE", 9, "full-rate production — most lucrative phase."),
        ("FOLLOW-ON", 5, "follow-on award — incumbent advantage."),
        ("INDEFINITE DELIVERY", 4, "IDIQ — task-order ceiling unlocks future revenue."),
    ]
    matched_themes = 0
    for kw, pts, note in themes:
        if kw in description:
            score += pts
            notes.append(note)
            matched_themes += 1
            if matched_themes >= 3:
                break

    score = max(0, min(int(score), 100))

    if score >= 70:
        verdict, color = "High Context", "#5c8a4f"
    elif score >= 45:
        verdict, color = "Moderate Context", "#c9a227"
    else:
        verdict, color = "Low Context", "#7a7468"

    return {"score": score, "verdict": verdict, "color": color, "notes": notes}


# ---------------------- Quick impact auto-tag ----------------------

def quick_impact_tag(award: dict, ticker: Optional[str], is_sm: bool) -> dict:
    """
    Cheap pre-tag computed at fetch time on every contract row, using only
    metadata (no per-row .info call). This auto-flags awards that look like
    they could move the stock so the UI can sort and badge them.

    Tag tiers:
      HIGH-IMPACT  -- small/mid-cap + strategic agency or narrative theme,
                       and meaningful absolute size.
      WATCH        -- matched ticker + at least one elevated factor.
      ROUTINE      -- has a ticker but no obvious elevation.
      NOISE        -- unmatched / no equity context.
    """
    amount = float(award.get("Award Amount") or 0)
    agency = (award.get("Awarding Agency") or "").upper()
    sub_agency = (award.get("Awarding Sub Agency") or "").upper()
    description = (award.get("Description") or "").upper()

    if not ticker:
        return {"tag": "NOISE", "color": MUTED_HEX, "rank": 3, "reasons": []}

    elevated = []
    strategic_top = ["DARPA", "SPACE FORCE", "BARDA", "INTELLIGENCE", "NASA"]
    if any(n in agency or n in sub_agency for n in strategic_top):
        elevated.append("strategic-customer")
    elif any(n in agency for n in ["DEFENSE", "NAVY", "ARMY", "AIR FORCE"]):
        elevated.append("dod-customer")

    narrative = ["HYPERSONIC", "QUANTUM", "ARTIFICIAL INTELLIGENCE",
                 "AUTONOMOUS", "UNMANNED", "SATELLITE", "VACCINE", "FULL RATE"]
    if any(k in description for k in narrative):
        elevated.append("narrative-theme")

    # Period of performance length proxy
    try:
        s = dt.datetime.fromisoformat(
            (award.get("Period of Performance Start Date") or "").split("T")[0]
        )
        e = dt.datetime.fromisoformat(
            (award.get("Period of Performance Current End Date") or "").split("T")[0]
        )
        years = (e - s).days / 365.25
        if years >= 4:
            elevated.append("multi-year")
    except Exception:
        pass

    # Materiality proxy on size alone (we don't have rev here)
    size_proxy = 0
    if amount >= 50_000_000:
        size_proxy = 2
    elif amount >= 15_000_000:
        size_proxy = 1

    # Compose
    if is_sm and (len(elevated) >= 2 or (len(elevated) >= 1 and size_proxy >= 1)):
        return {"tag": "HIGH-IMPACT", "color": HIGH_HEX, "rank": 0, "reasons": elevated}
    if is_sm and len(elevated) >= 1:
        return {"tag": "WATCH", "color": WATCH_HEX, "rank": 1, "reasons": elevated}
    if ticker and len(elevated) >= 2 and size_proxy >= 1:
        # mega-cap with strong setup is still worth watching
        return {"tag": "WATCH", "color": WATCH_HEX, "rank": 1, "reasons": elevated}
    if ticker:
        return {"tag": "ROUTINE", "color": ROUTINE_HEX, "rank": 2, "reasons": elevated}
    return {"tag": "NOISE", "color": MUTED_HEX, "rank": 3, "reasons": []}


# Tag colors (kept here so the UI can import the same constants)
HIGH_HEX    = "#ff2020"
WATCH_HEX   = "#ff6464"
ROUTINE_HEX = "#7a7468"
MUTED_HEX   = "#5a5a5a"


# ---------------------- Speculative investment thesis ----------------------

def speculative_thesis(award: dict, info: Optional[dict] = None) -> list[dict]:
    """
    Construct contract-driven angles for why the award itself might lift
    the stock. These are equity *theses* derived from contract characteristics
    — distinct from the indicator-based context score.

    Each thesis is a {title, body} dict so the UI can render structured
    bullets. Tone is speculative-but-grounded; we intentionally use phrases
    like 'historically', 'often', 'tends to'.
    """
    amount = float(award.get("Award Amount") or 0)
    agency = (award.get("Awarding Agency") or "").upper()
    sub_agency = (award.get("Awarding Sub Agency") or "").upper()
    description = (award.get("Description") or "").upper()

    theses: list[dict] = []

    # 1. Customer validation tier
    strategic_top = ["DARPA", "SPACE FORCE", "NASA", "BARDA", "INTELLIGENCE"]
    if any(n in agency or n in sub_agency for n in strategic_top):
        theses.append({
            "title": "Strategic customer validation",
            "body": (
                "An award from a top-tier strategic customer historically de-risks "
                "enterprise sales pipelines. Commercial buyers regularly cite "
                "federal adoption as a procurement justification, and analysts "
                "tend to mark up 'addressable market' assumptions after these "
                "awards. Watch for follow-on commercial announcements within "
                "1-2 quarters."
            ),
        })
    elif any(n in agency for n in ["DEFENSE", "NAVY", "ARMY", "AIR FORCE"]):
        theses.append({
            "title": "DoD incumbency lock-in",
            "body": (
                "Department of Defense incumbency creates structural lock-in: "
                "qualification windows for new entrants are long, certification "
                "requirements steep. An initial contract often sets up multi-year "
                "share gain across the program-of-record cycle."
            ),
        })

    # 2. Materiality re-rating
    if info and info.get("totalRevenue"):
        rev = info["totalRevenue"]
        if rev > 0:
            ratio = amount / rev
            if ratio > 0.25:
                theses.append({
                    "title": "Materiality re-rating potential",
                    "body": (
                        f"At ~{ratio*100:.0f}% of trailing revenue, this single "
                        "award could materially shift consensus revenue and EPS "
                        "trajectories once recognized. Sell-side estimates "
                        "typically lag award announcements by 1-3 weeks — equity "
                        "often reacts first, then resets on the next earnings print."
                    ),
                })
            elif ratio > 0.10:
                theses.append({
                    "title": "Backlog accretion",
                    "body": (
                        f"~{ratio*100:.0f}% of trailing revenue is meaningful "
                        "backlog accretion. Backlog/revenue ratio is a commonly "
                        "tracked multiple-expansion driver for defense and "
                        "gov-tech names — incremental coverage looks at it."
                    ),
                })
            elif ratio > 0.02:
                theses.append({
                    "title": "Modest top-line contribution",
                    "body": (
                        f"At {ratio*100:.1f}% of trailing revenue, financial "
                        "impact alone is unlikely to move the stock — the equity "
                        "case rests on what the contract signals (customer, "
                        "scope, follow-on potential), not the dollar amount."
                    ),
                })

    # 3. Period of performance
    try:
        s = dt.datetime.fromisoformat(
            (award.get("Period of Performance Start Date") or "").split("T")[0]
        )
        e = dt.datetime.fromisoformat(
            (award.get("Period of Performance Current End Date") or "").split("T")[0]
        )
        years = (e - s).days / 365.25
        if years >= 4:
            theses.append({
                "title": "Recurring-revenue tail",
                "body": (
                    f"A {years:.1f}-year period of performance creates a "
                    "predictable revenue stream the market typically values at "
                    "higher multiples than one-time project work. Even hardware "
                    "programs accrue SaaS-like stickiness over multi-year tails."
                ),
            })
        elif 2 <= years < 4:
            theses.append({
                "title": "Multi-year visibility",
                "body": (
                    f"A {years:.1f}-year horizon adds revenue visibility that "
                    "supports forward guidance. Companies often raise long-term "
                    "targets during the quarters following such awards."
                ),
            })
    except Exception:
        pass

    # 4. Production / follow-on phase
    if "FULL RATE" in description or "FULL-RATE" in description:
        theses.append({
            "title": "Full-rate production economics",
            "body": (
                "Full-rate production marks the transition out of cost-plus R&D "
                "into fixed-price unit economics. Gross margins expand as "
                "overhead amortizes across higher volumes — historically the "
                "most lucrative phase of a defense program lifecycle."
            ),
        })
    elif "PRODUCTION" in description and "DEVELOPMENT" not in description:
        theses.append({
            "title": "Past R&D, into recurring margin",
            "body": (
                "Production-phase awards signal that technical risk is behind "
                "the program. Margins typically improve relative to the initial "
                "R&D phase, and revenue becomes more predictable."
            ),
        })
    if "FOLLOW-ON" in description or "FOLLOW ON" in description:
        theses.append({
            "title": "Incumbent advantage on re-competes",
            "body": (
                "Follow-on awards reflect proven performance and switching "
                "costs. Incumbents win the vast majority of program-of-record "
                "extensions - re-competitions require demonstrated technical "
                "heritage that newcomers cannot easily replicate."
            ),
        })

    # 5. Narrative themes - these are the angles funds use for sentiment
    narrative_themes = [
        ("QUANTUM",
         "Quantum is a small but premium-multiple narrative - generalist "
         "funds with mandate to allocate to the theme have limited "
         "public-market liquidity options, which concentrates buying."),
        ("HYPERSONIC",
         "Hypersonic programs are a Pentagon priority through the late "
         "2020s. Primes and subcomponent providers benefit from scarcity "
         "and accelerating obligation rates."),
        ("ARTIFICIAL INTELLIGENCE",
         "AI in defense scope of work signals capability differentiation "
         "and frequently unlocks larger commercial sales motions in the "
         "subsequent quarters."),
        ("AUTONOMOUS",
         "Autonomy and unmanned systems is a trending procurement category. "
         "Small-cap exposure trades at growth-tech-like multiples even when "
         "underlying margins are hardware-typical."),
        ("SATELLITE",
         "Space-segment is a multi-decade infrastructure theme. Recurring "
         "data, imagery, and launch revenue compound - a single award often "
         "anchors a multi-contract relationship."),
        ("VACCINE",
         "BARDA and vaccine awards historically come with stockpile "
         "renewal options. A single award frequently signals a multi-year "
         "purchase commitment beyond the headline number."),
        ("CYBER",
         "Cybersecurity spend is among the most defensive federal line "
         "items. Programs in scope rarely shrink, and award velocity has "
         "outpaced overall IT spend through the 2020s."),
    ]
    for kw, body in narrative_themes:
        if kw in description:
            theses.append({"title": f"{kw.title()} narrative tailwind", "body": body})
            break

    # 6. IDIQ / ceiling optionality
    if "INDEFINITE DELIVERY" in description or "IDIQ" in description.upper():
        theses.append({
            "title": "IDIQ ceiling = embedded optionality",
            "body": (
                "Indefinite-delivery contracts establish a maximum task-order "
                "ceiling. The initial obligation may be modest, but the ceiling "
                "itself represents future revenue capacity that gets re-rated "
                "as task orders are placed against it."
            ),
        })

    # 7. Default - modest awards without an obvious thesis
    if not theses:
        theses.append({
            "title": "Limited contract-driven thesis",
            "body": (
                "This particular award doesn't surface obvious equity catalysts: "
                "moderate size, routine agency, no narrative theme in scope. "
                "Any stock thesis here probably rests on factors outside the "
                "contract itself."
            ),
        })

    return theses
