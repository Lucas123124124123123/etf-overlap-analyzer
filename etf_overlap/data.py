"""Read and write the holdings snapshots stored under ``data/``."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .providers import COLUMNS, Holdings

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
HOLDINGS_DIR = DATA_DIR / "holdings"
FUNDS_FILE = DATA_DIR / "funds.csv"

FUND_COLUMNS = ["fund", "fund_name", "issuer", "as_of", "holdings"]


def save_holdings(h: Holdings, data_dir: Path = DATA_DIR) -> None:
    holdings_dir = data_dir / "holdings"
    holdings_dir.mkdir(parents=True, exist_ok=True)
    h.positions[COLUMNS].to_csv(holdings_dir / f"{h.fund}.csv", index=False, float_format="%.6f")

    funds_file = data_dir / "funds.csv"
    funds = pd.read_csv(funds_file) if funds_file.exists() else pd.DataFrame(columns=FUND_COLUMNS)
    row = {"fund": h.fund, "fund_name": h.fund_name, "issuer": h.issuer, "as_of": h.as_of.isoformat(), "holdings": len(h.positions)}
    funds = pd.concat([funds[funds["fund"] != h.fund], pd.DataFrame([row])], ignore_index=True)
    funds.sort_values("fund").to_csv(funds_file, index=False)


def load_funds(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    return pd.read_csv(data_dir / "funds.csv").set_index("fund")


def load_holdings(funds: list[str], data_dir: Path = DATA_DIR) -> dict[str, pd.DataFrame]:
    return {f: pd.read_csv(data_dir / "holdings" / f"{f}.csv", keep_default_na=False) for f in funds}
