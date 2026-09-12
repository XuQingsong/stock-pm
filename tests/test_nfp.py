from __future__ import annotations

import json
from pathlib import Path

from stock_pm.fetch import FetchResult
from stock_pm.nfp import NFP_SERIES, nfp_from_payems, sync_nfp_from_fred
from stock_pm.series import parse_fred_observations


def test_nfp_from_payems_is_monthly_difference():
    fixture = json.loads(Path(NFP_SERIES["fixture"]).read_text())
    rows = parse_fred_observations(fixture)
    derived = nfp_from_payems(rows)
    assert derived is not None
    assert derived["period"] == "2026-08-01"
    assert derived["value"] == 220.0
    assert derived["payems_level"] == 159832.0
    assert derived["prior_level"] == 159612.0


def test_nfp_from_payems_needs_two_prints():
    assert nfp_from_payems([{"period": "2026-08-01", "value": 159832}]) is None
    assert nfp_from_payems([]) is None


def test_sync_nfp_from_official_csv(monkeypatch):
    csv = "observation_date,PAYEMS\n2026-08-01,159832\n2026-07-01,159612\n"

    def fake_text(url, **kwargs):
        assert "id=PAYEMS" in url
        assert "fredgraph.csv" in url
        return FetchResult(
            payload=csv,
            status="ok",
            reason_code="within_threshold",
            fetched_at="2026-09-12T12:00:00+00:00",
            from_cache=False,
            http_source=url,
            transport="fredgraph_csv",
        )

    stored = []
    monkeypatch.setattr("stock_pm.series.text_get", fake_text)
    rec = sync_nfp_from_fred(store=stored.append)
    assert rec["status"] == "ok"
    assert rec["value"] == 220.0
    assert rec["as_of"] == "2026-08-01"
    assert rec["series_or_symbol"] == "PAYEMS"
    assert rec["unit"] == "thousands"
    assert rec["source"] == "FRED"
    assert stored[0]["event_type"] == "nfp"
    assert stored[0]["actual"] == 220.0
    assert "apikey" not in str(rec).lower()
