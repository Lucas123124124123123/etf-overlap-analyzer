from datetime import date

import pandas as pd

from etf_overlap.data import load_funds, load_holdings, save_holdings
from etf_overlap.providers import Holdings


def make_holdings(fund: str, as_of: date) -> Holdings:
    positions = pd.DataFrame({"ticker": ["AAA", "BBB"], "name": ["Alpha", "Beta"], "weight": [60.0, 40.0]})
    return Holdings(fund, f"{fund} Fund", "Test Issuer", as_of, positions)


def test_save_and_load_round_trip(tmp_path):
    save_holdings(make_holdings("ABC", date(2026, 1, 2)), tmp_path)

    funds = load_funds(tmp_path)
    assert funds.loc["ABC", "fund_name"] == "ABC Fund"
    assert funds.loc["ABC", "holdings"] == 2

    loaded = load_holdings(["ABC"], tmp_path)["ABC"]
    assert loaded["ticker"].tolist() == ["AAA", "BBB"]
    assert loaded["weight"].sum() == 100.0


def test_saving_again_replaces_the_fund_row(tmp_path):
    save_holdings(make_holdings("ABC", date(2026, 1, 2)), tmp_path)
    save_holdings(make_holdings("XYZ", date(2026, 1, 2)), tmp_path)
    save_holdings(make_holdings("ABC", date(2026, 2, 3)), tmp_path)

    funds = load_funds(tmp_path)
    assert list(funds.index) == ["ABC", "XYZ"]
    assert funds.loc["ABC", "as_of"] == "2026-02-03"
