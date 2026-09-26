"""Overlap and look-through math.

All weights are percentages (0-100). ``holdings`` maps a fund ticker to a
DataFrame with columns ``ticker``, ``name`` and ``weight``.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import pandas as pd


@dataclass
class PairOverlap:
    fund_a: str
    fund_b: str
    weight_overlap: float  # % of money that sits in the same stocks in both funds
    common_count: int
    count_a: int
    count_b: int
    common: pd.DataFrame  # ticker, name, weight_a, weight_b, overlap

    @property
    def share_of_a(self) -> float:
        """% of fund A's holdings (by count) that also appear in fund B."""
        return 100 * self.common_count / self.count_a if self.count_a else 0.0

    @property
    def share_of_b(self) -> float:
        return 100 * self.common_count / self.count_b if self.count_b else 0.0


def pair_overlap(fund_a: str, a: pd.DataFrame, fund_b: str, b: pd.DataFrame) -> PairOverlap:
    """Weight overlap = sum over shared stocks of the smaller of the two weights.

    It answers "what % of my money is invested the same way in both funds".
    Two identical funds score 100, two funds with nothing in common score 0.
    """
    merged = a[["ticker", "name", "weight"]].merge(
        b[["ticker", "weight"]], on="ticker", suffixes=("_a", "_b")
    )
    merged["overlap"] = merged[["weight_a", "weight_b"]].min(axis=1)
    merged = merged.sort_values("overlap", ascending=False, ignore_index=True)
    return PairOverlap(
        fund_a=fund_a,
        fund_b=fund_b,
        weight_overlap=float(merged["overlap"].sum()),
        common_count=len(merged),
        count_a=len(a),
        count_b=len(b),
        common=merged,
    )


def overlap_matrix(holdings: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Symmetric fund-by-fund table of weight overlap (diagonal = 100)."""
    funds = list(holdings)
    matrix = pd.DataFrame(100.0, index=funds, columns=funds)
    for fa, fb in combinations(funds, 2):
        value = pair_overlap(fa, holdings[fa], fb, holdings[fb]).weight_overlap
        matrix.loc[fa, fb] = matrix.loc[fb, fa] = value
    return matrix


def redundant_pairs(matrix: pd.DataFrame, threshold: float = 50.0) -> list[tuple[str, str, float]]:
    """Fund pairs whose overlap is at or above ``threshold``, highest first."""
    pairs = [
        (fa, fb, float(matrix.loc[fa, fb]))
        for fa, fb in combinations(matrix.index, 2)
        if matrix.loc[fa, fb] >= threshold
    ]
    return sorted(pairs, key=lambda p: p[2], reverse=True)


def look_through(holdings: dict[str, pd.DataFrame], allocation: dict[str, float]) -> pd.DataFrame:
    """What you actually own: exposure to each stock across the whole portfolio.

    ``allocation`` is how the money is split between funds, in any unit
    (dollars or percentages); it is rescaled to sum to 100%.
    Returns one row per stock with ``exposure`` (% of the portfolio) and one
    column per fund showing how much of that exposure comes from it.
    """
    total = sum(v for v in allocation.values() if v > 0)
    if total <= 0:
        raise ValueError("Allocation must contain at least one positive amount")

    parts = []
    for fund, amount in allocation.items():
        if amount <= 0:
            continue
        df = holdings[fund][["ticker", "name", "weight"]].copy()
        df["fund"] = fund
        df["contribution"] = df["weight"] * amount / total
        parts.append(df)
    long = pd.concat(parts, ignore_index=True)

    # Some issuers publish names in ALL CAPS; prefer a mixed-case spelling when one exists.
    ranked = long.assign(_caps=long["name"].str.isupper()).sort_values("_caps", kind="stable")
    names = ranked.drop_duplicates("ticker").set_index("ticker")["name"]
    by_fund = long.pivot_table(
        index="ticker", columns="fund", values="contribution", aggfunc="sum", fill_value=0.0
    )
    by_fund.columns.name = None
    out = by_fund.copy()
    out.insert(0, "exposure", by_fund.sum(axis=1))
    out.insert(0, "name", names.reindex(out.index))
    out["funds_holding"] = (by_fund > 0).sum(axis=1)
    return out.sort_values("exposure", ascending=False).reset_index()


@dataclass
class Concentration:
    stocks: int
    top10_share: float  # % of the portfolio in its 10 biggest stocks
    effective_stocks: float  # diversification expressed as N equally weighted stocks


def concentration(exposure: pd.DataFrame) -> Concentration:
    """Summarize how concentrated a look-through portfolio really is.

    ``effective_stocks`` is the inverse Herfindahl index: a portfolio with
    500 stocks but most money in 10 of them behaves like far fewer stocks.
    """
    weights = exposure["exposure"]
    shares = weights / weights.sum()
    return Concentration(
        stocks=int((weights > 0).sum()),
        top10_share=float(weights.nlargest(10).sum() / weights.sum() * 100),
        effective_stocks=float(1 / (shares**2).sum()),
    )
