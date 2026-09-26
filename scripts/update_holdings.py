"""Refresh the holdings snapshots in data/ from the issuers' websites.

Usage:
    python scripts/update_holdings.py              # refresh every fund
    python scripts/update_holdings.py SPY QQQ      # refresh some funds
    python scripts/update_holdings.py --file QQQ qqq.json
        # import a file you downloaded manually (issuer blocked the script)

A fund that fails to download keeps its previous snapshot, so one
flaky website never breaks the whole dataset.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etf_overlap.data import save_holdings  # noqa: E402
from etf_overlap.providers import PROVIDERS, parse_invesco_json, parse_ssga_xlsx  # noqa: E402

# Fund ticker -> issuer. Add a line here to support a new ETF.
FUNDS = {
    "SPY": "ssga",   # S&P 500
    "SPYG": "ssga",  # S&P 500 Growth
    "SPYV": "ssga",  # S&P 500 Value
    "SPYD": "ssga",  # S&P 500 High Dividend
    "SDY": "ssga",   # S&P High Yield Dividend Aristocrats
    "MDY": "ssga",   # S&P MidCap 400
    "XLK": "ssga",   # Technology
    "XLF": "ssga",   # Financials
    "XLV": "ssga",   # Health Care
    "XLE": "ssga",   # Energy
    "XLY": "ssga",   # Consumer Discretionary
    "XLC": "ssga",   # Communication Services
    "XLI": "ssga",   # Industrials
    "XLP": "ssga",   # Consumer Staples
    "QQQ": "invesco",  # Nasdaq-100
}


def import_file(fund: str, path: Path) -> None:
    fund = fund.upper()
    if path.suffix == ".json":
        holdings = parse_invesco_json(json.loads(path.read_text(encoding="utf-8")), fund)
    else:
        holdings = parse_ssga_xlsx(path.read_bytes(), fund)
    save_holdings(holdings)
    print(f"{fund}: imported {len(holdings.positions)} holdings as of {holdings.as_of}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("funds", nargs="*", help="fund tickers to refresh (default: all)")
    parser.add_argument("--file", nargs=2, metavar=("FUND", "PATH"), help="import a manually downloaded file")
    args = parser.parse_args()

    if args.file:
        import_file(args.file[0], Path(args.file[1]))
        return 0

    session = requests.Session()
    failed = []
    for fund in [f.upper() for f in args.funds] or list(FUNDS):
        provider = FUNDS.get(fund)
        if provider is None:
            print(f"{fund}: unknown fund, add it to FUNDS in this script")
            failed.append(fund)
            continue
        try:
            holdings = PROVIDERS[provider](fund, session)
        except (requests.RequestException, ValueError, KeyError) as exc:
            print(f"{fund}: download failed ({exc}); keeping previous snapshot")
            failed.append(fund)
            continue
        save_holdings(holdings)
        print(f"{fund}: {len(holdings.positions)} holdings as of {holdings.as_of}")

    if failed:
        print(f"\nNot updated: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
