import pandas as pd
import pytest

from etf_overlap.overlap import concentration, look_through, overlap_matrix, pair_overlap, redundant_pairs


def fund(rows):
    return pd.DataFrame(rows, columns=["ticker", "name", "weight"])


A = fund([("AAA", "Alpha", 50.0), ("BBB", "Beta", 30.0), ("CCC", "Gamma", 20.0)])
B = fund([("AAA", "Alpha", 20.0), ("BBB", "Beta", 40.0), ("DDD", "Delta", 40.0)])
C = fund([("XXX", "Xray", 100.0)])


def test_identical_funds_overlap_fully():
    assert pair_overlap("A", A, "A2", A.copy()).weight_overlap == pytest.approx(100.0)


def test_disjoint_funds_do_not_overlap():
    result = pair_overlap("A", A, "C", C)
    assert result.weight_overlap == 0
    assert result.common_count == 0


def test_weight_overlap_takes_smaller_weight_of_each_shared_stock():
    result = pair_overlap("A", A, "B", B)
    # AAA: min(50, 20) = 20, BBB: min(30, 40) = 30
    assert result.weight_overlap == pytest.approx(50.0)
    assert result.common_count == 2
    assert result.share_of_a == pytest.approx(200 / 3)
    assert list(result.common["ticker"]) == ["BBB", "AAA"]


def test_overlap_matrix_is_symmetric_with_full_diagonal():
    m = overlap_matrix({"A": A, "B": B, "C": C})
    assert (m.values == m.values.T).all()
    assert list(m.values.diagonal()) == [100.0, 100.0, 100.0]
    assert m.loc["A", "B"] == pytest.approx(50.0)


def test_redundant_pairs_filters_by_threshold():
    m = overlap_matrix({"A": A, "B": B, "C": C})
    assert redundant_pairs(m, threshold=50) == [("A", "B", pytest.approx(50.0))]
    assert redundant_pairs(m, threshold=60) == []


def test_look_through_combines_funds_by_allocation():
    exposure = look_through({"A": A, "B": B}, {"A": 5000, "B": 5000}).set_index("ticker")
    assert exposure.loc["AAA", "exposure"] == pytest.approx(35.0)  # (50 + 20) / 2
    assert exposure.loc["BBB", "exposure"] == pytest.approx(35.0)
    assert exposure.loc["DDD", "exposure"] == pytest.approx(20.0)
    assert exposure.loc["AAA", "A"] == pytest.approx(25.0)
    assert exposure.loc["AAA", "funds_holding"] == 2
    assert exposure["exposure"].sum() == pytest.approx(100.0)


def test_look_through_ignores_zero_allocations():
    exposure = look_through({"A": A, "C": C}, {"A": 1, "C": 0})
    assert "XXX" not in set(exposure["ticker"])
    assert exposure["exposure"].sum() == pytest.approx(100.0)


def test_look_through_rejects_empty_allocation():
    with pytest.raises(ValueError):
        look_through({"A": A}, {"A": 0})


def test_look_through_prefers_mixed_case_names():
    upper = fund([("AAA", "ALPHA INC", 100.0)])
    mixed = fund([("AAA", "Alpha Inc", 100.0)])
    exposure = look_through({"U": upper, "M": mixed}, {"U": 1, "M": 1})
    assert exposure.loc[0, "name"] == "Alpha Inc"


def test_concentration_of_equal_weights():
    exposure = pd.DataFrame({"exposure": [25.0, 25.0, 25.0, 25.0]})
    c = concentration(exposure)
    assert c.stocks == 4
    assert c.effective_stocks == pytest.approx(4.0)
    assert c.top10_share == pytest.approx(100.0)
