from __future__ import annotations

from wikiskill import present
from wikiskill.compare import Rate


def test_a_rate_gives_counts_rate_and_interval():
    assert present.rate(9, 10) == "9/10 (90%, 60-98%)"
    assert present.of(Rate(9, 10)) == "9/10 (90%, 60-98%)"


def test_nothing_counted_is_missing():
    assert present.rate(0, 0) == present.MISSING == "—"
    assert present.count(0, 0) == "—"
    assert present.of(None) == present.count_of(None) == "—"


def test_counts_and_percentages():
    assert present.count(3, 4) == "3/4"
    assert present.pct(0.25) == "25%"
    assert present.pct(0.25, signed=True) == "+25%"
    assert present.pct(-0.1, signed=True) == "-10%"
    assert present.pct(None) == "—"
    assert present.seconds(1500) == "1.5"
    assert present.value(None) == present.value("") == "—"
    assert present.value(2.5, "g") == "2.5"


def test_a_table():
    assert present.table(["a", "b"], [[1, "x"]]) == ["| a | b |", "|---|---|", "| 1 | x |"]
