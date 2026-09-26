import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import requests

from etf_overlap.providers import (
    clean_positions,
    fetch_invesco,
    fetch_ssga,
    normalize_ticker,
    parse_invesco_json,
    parse_ssga_xlsx,
)

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


class FakeResponse:
    def __init__(self, status: int, content: bytes = b"", payload: dict | None = None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self.content = content
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(f"{self.status_code} error")


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return self.responses.pop(0)


def test_fetch_ssga_downloads_the_fund_spreadsheet():
    content = (FIXTURES / "ssga_xlk.xlsx").read_bytes()
    session = FakeSession([FakeResponse(200, content)])
    h = fetch_ssga("XLK", session)
    assert session.urls[0].endswith("holdings-daily-us-en-xlk.xlsx")
    assert h.fund == "XLK"


def test_fetch_invesco_retries_after_a_406(monkeypatch):
    monkeypatch.setattr("etf_overlap.providers.time.sleep", lambda _: None)
    payload = json.loads((FIXTURES / "invesco_qqq.json").read_text(encoding="utf-8"))
    session = FakeSession(
        [
            FakeResponse(406),
            FakeResponse(200, b"{}", payload),
            FakeResponse(200, b"{}", {"fundName": "Invesco QQQ Trust"}),
        ]
    )
    h = fetch_invesco("QQQ", session)
    assert h.fund_name == "Invesco QQQ Trust"
    assert len(session.urls) == 3


def test_fetch_invesco_gives_up_after_all_attempts(monkeypatch):
    monkeypatch.setattr("etf_overlap.providers.time.sleep", lambda _: None)
    session = FakeSession([FakeResponse(406)] * 4)
    with pytest.raises(requests.HTTPError):
        fetch_invesco("QQQ", session)
