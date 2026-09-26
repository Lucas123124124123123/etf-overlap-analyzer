"""Download and normalize ETF holdings from issuer websites.

Every provider returns the same shape: a DataFrame with columns
``ticker``, ``name`` and ``weight`` (percent of fund net assets, 0-100),
containing only equity positions (cash, futures and money-market sweeps
are dropped because they are not "stocks you own").
"""

from __future__ import annotations

import html
import io
import re
import time
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd
import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
)

COLUMNS = ["ticker", "name", "weight"]

# A plain US listing: 1-5 letters, optionally a share class (BRK.B, MOG.A).
_TICKER_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")
# Futures show up as e.g. "XAK TECHNOLOGY    DEC26".
_FUTURES_RE = re.compile(r"\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}\b")
_NON_EQUITY_NAMES = re.compile(r"MONEY MARKET|U\.?S\.? DOLLAR|CASH", re.IGNORECASE)


@dataclass
class Holdings:
    fund: str
    fund_name: str
    issuer: str
    as_of: date
    positions: pd.DataFrame


def normalize_ticker(raw: object) -> str:
    """Map issuer-specific spellings to one format: 'BRK/B', 'brk b' -> 'BRK.B'."""
    ticker = str(raw).strip().upper()
    return re.sub(r"[/\s]+", ".", ticker)


def clean_positions(df: pd.DataFrame) -> pd.DataFrame:
    """Keep equity rows only, merge duplicate tickers and sort by weight."""
    out = df[COLUMNS].copy()
    out["ticker"] = out["ticker"].map(normalize_ticker)
    out["name"] = out["name"].astype(str).str.strip()
    out["weight"] = pd.to_numeric(out["weight"], errors="coerce")

    is_equity = (
        out["ticker"].str.match(_TICKER_RE)
        & ~out["name"].str.contains(_FUTURES_RE)
        & ~out["name"].str.contains(_NON_EQUITY_NAMES)
        & (out["weight"] > 0)
    )
    out = out[is_equity]
    out = out.groupby("ticker", as_index=False).agg(name=("name", "first"), weight=("weight", "sum"))
    return out.sort_values("weight", ascending=False, ignore_index=True)


# --- State Street (SPDR) -------------------------------------------------

SSGA_URL = (
    "https://www.ssga.com/us/en/intermediary/library-content/products/"
    "fund-data/etfs/us/holdings-daily-us-en-{ticker}.xlsx"
)


def parse_ssga_xlsx(content: bytes, fund: str) -> Holdings:
    """Parse the daily holdings spreadsheet SPDR publishes for each ETF."""
    raw = pd.read_excel(io.BytesIO(content), header=None)
    header_row = raw.index[raw.iloc[:, 0].astype(str).str.strip() == "Name"][0]

    fund_name = str(raw.iloc[0, 1]).replace("�", "").strip()
    as_of_text = str(raw.iloc[2, 1]).replace("As of", "").strip()
    as_of = datetime.strptime(as_of_text, "%d-%b-%Y").date()

    table = raw.iloc[header_row + 1 :].copy()
    table.columns = [str(c).strip() for c in raw.iloc[header_row]]
    table = table.dropna(subset=["Ticker"])
    table = table.rename(columns={"Ticker": "ticker", "Name": "name", "Weight": "weight"})
    return Holdings(fund.upper(), fund_name, "State Street SPDR", as_of, clean_positions(table))


def fetch_ssga(fund: str, session: requests.Session | None = None) -> Holdings:
    session = session or requests.Session()
    resp = session.get(SSGA_URL.format(ticker=fund.lower()), headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    return parse_ssga_xlsx(resp.content, fund)


# --- Invesco -------------------------------------------------------------

INVESCO_URL = (
    "https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/{ticker}/"
    "holdings/fund?idType=ticker&interval=monthly&productType=ETF"
)
INVESCO_FUND_URL = (
    "https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/{ticker}"
    "?idType=ticker&variationType=fundDetails&productType=ETF"
)
# The API answers 406 unless the request looks like it came from invesco.com.
INVESCO_HEADERS = {"User-Agent": USER_AGENT, "Accept": "*/*", "Origin": "https://www.invesco.com"}


def parse_invesco_json(payload: dict, fund: str, fund_name: str | None = None) -> Holdings:
    rows = [
        {
            "ticker": h.get("ticker") or "",
            "name": html.unescape(h.get("issuerName") or ""),
            "weight": h.get("percentageOfTotalNetAssets"),
        }
        for h in payload.get("holdings", [])
        if not re.search(r"Currency|Future|Cash", h.get("securityTypeName") or "", re.IGNORECASE)
    ]
    as_of = datetime.strptime(payload["effectiveDate"], "%Y-%m-%d").date()
    positions = clean_positions(pd.DataFrame(rows, columns=COLUMNS))
    return Holdings(fund.upper(), fund_name or f"Invesco {fund.upper()}", "Invesco", as_of, positions)


def _get_invesco(session: requests.Session, url: str, attempts: int = 4) -> requests.Response:
    # The CDN in front of the API sometimes caches a 406; a cache-busting
    # query parameter plus a short retry usually gets a fresh answer.
    resp = None
    for attempt in range(attempts):
        resp = session.get(f"{url}&_={int(time.time() * 1000)}", headers=INVESCO_HEADERS, timeout=30)
        if resp.ok and resp.content:
            return resp
        time.sleep(1.5 * (attempt + 1))
    resp.raise_for_status()
    raise requests.HTTPError(f"Empty response from {url}", response=resp)


def fetch_invesco(fund: str, session: requests.Session | None = None) -> Holdings:
    session = session or requests.Session()
    payload = _get_invesco(session, INVESCO_URL.format(ticker=fund.upper())).json()
    try:
        fund_name = _get_invesco(session, INVESCO_FUND_URL.format(ticker=fund.upper()), attempts=1).json().get("fundName")
    except requests.RequestException:
        fund_name = None
    return parse_invesco_json(payload, fund, fund_name)


PROVIDERS = {"ssga": fetch_ssga, "invesco": fetch_invesco}
