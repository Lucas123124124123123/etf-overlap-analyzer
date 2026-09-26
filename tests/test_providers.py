import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from etf_overlap.providers import clean_positions, normalize_ticker, parse_invesco_json, parse_ssga_xlsx

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("raw, expected", [("brk b", "BRK.B"), ("BRK/B", "BRK.B"), (" aapl ", "AAPL")])
def test_normalize_ticker(raw, expected):
    assert normalize_ticker(raw) == expected


def test_clean_positions_drops_cash_futures_and_bad_rows():
    raw = pd.DataFrame(
        [
            ("AAPL", "APPLE INC", 7.0),
            ("-", "US DOLLAR", 0.2),
            ("CASH_USD", "U.S. Dollar", 0.8),
            ("IXTZ6", "XAK TECHNOLOGY    DEC26", 0.1),
            ("-", "SSI US GOV MONEY MARKET CLASS", 0.1),
            ("2602335D", "TPG INC", 0.00001),
            ("MSFT", "MICROSOFT CORP", 5.0),
            ("NEG", "Short position", -1.0),
        ],
        columns=["ticker", "name", "weight"],
    )
    out = clean_positions(raw)
    assert list(out["ticker"]) == ["AAPL", "MSFT"]


def test_clean_positions_merges_duplicate_tickers():
    raw = pd.DataFrame([("AAPL", "Apple", 1.0), ("AAPL", "Apple", 2.0)], columns=["ticker", "name", "weight"])
    assert clean_positions(raw)["weight"].tolist() == [3.0]


def test_parse_ssga_xlsx():
    h = parse_ssga_xlsx((FIXTURES / "ssga_xlk.xlsx").read_bytes(), "xlk")
    assert h.fund == "XLK"
    assert h.fund_name == "Technology Select Sector SPDR ETF"
    assert h.as_of == date(2026, 9, 24)
    assert h.positions.loc[0, "ticker"] == "NVDA"
    assert not h.positions["ticker"].isin(["-", "IXTZ6"]).any()
    assert 99 < h.positions["weight"].sum() < 100.5


def test_parse_invesco_json():
    payload = json.loads((FIXTURES / "invesco_qqq.json").read_text(encoding="utf-8"))
    h = parse_invesco_json(payload, "qqq", "Invesco QQQ Trust")
    tickers = set(h.positions["ticker"])
    assert h.fund == "QQQ"
    assert h.as_of == date(2026, 9, 24)
    assert {"NVDA", "ASML", "ARM"} <= tickers  # ADRs are kept
    assert not tickers & {"USD", "NQZ6", "USDPDV"}  # cash and futures are not
    assert len(h.positions) == 101
