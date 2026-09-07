from stock_pm.cboe import parse_cboe_html, snapshot_from_options_data

SAMPLE_DATA = {
    "ratios": [
        {"name": "TOTAL PUT/CALL RATIO", "value": "0.76"},
        {"name": "INDEX PUT/CALL RATIO", "value": "0.89"},
        {"name": "EXCHANGE TRADED PRODUCTS PUT/CALL RATIO", "value": "0.85"},
        {"name": "EQUITY PUT/CALL RATIO", "value": "0.58"},
        {"name": "CBOE VOLATILITY INDEX (VIX) PUT/CALL RATIO", "value": "0.21"},
        {"name": "SPX + SPXW PUT/CALL RATIO", "value": "1.15"},
    ],
    "SUM OF ALL PRODUCTS": [
        {"name": "VOLUME", "call": 8097199, "put": 6151527, "total": 14248726},
        {"name": "OPEN INTEREST", "call": 1, "put": 1, "total": 2},
    ],
    "INDEX OPTIONS": [
        {"name": "VOLUME", "call": 3326202, "put": 2956282, "total": 6282484},
    ],
    "EXCHANGE TRADED PRODUCTS": [
        {"name": "VOLUME", "call": 1581817, "put": 1349256, "total": 2931073},
    ],
    "EQUITY OPTIONS": [
        {"name": "VOLUME", "call": 3189180, "put": 1845989, "total": 5035169},
    ],
}

ESCAPED_HTML = (
    'selectedDate\\":\\"2026-09-04\\",\\"minDate\\":\\"2019-10-07\\"'
    'optionsData\\":{\\"ratios\\":[{\\"name\\":\\"TOTAL PUT/CALL RATIO\\",\\"value\\":\\"0.76\\"},'
    '{\\"name\\":\\"INDEX PUT/CALL RATIO\\",\\"value\\":\\"0.89\\"},'
    '{\\"name\\":\\"EXCHANGE TRADED PRODUCTS PUT/CALL RATIO\\",\\"value\\":\\"0.85\\"},'
    '{\\"name\\":\\"EQUITY PUT/CALL RATIO\\",\\"value\\":\\"0.58\\"}],'
    '\\"SUM OF ALL PRODUCTS\\":[{\\"name\\":\\"VOLUME\\",\\"call\\":100,\\"put\\":80,\\"total\\":180}],'
    '\\"INDEX OPTIONS\\":[{\\"name\\":\\"VOLUME\\",\\"call\\":40,\\"put\\":50,\\"total\\":90}],'
    '\\"EXCHANGE TRADED PRODUCTS\\":[{\\"name\\":\\"VOLUME\\",\\"call\\":20,\\"put\\":10,\\"total\\":30}],'
    '\\"EQUITY OPTIONS\\":[{\\"name\\":\\"VOLUME\\",\\"call\\":40,\\"put\\":20,\\"total\\":60}]}'
)


def test_snapshot_builds_call_put_and_mix() -> None:
    snap = snapshot_from_options_data(SAMPLE_DATA, "2026-09-04")
    assert snap["trade_date"] == "2026-09-04"
    assert snap["total_volume"] == 14248726
    assert snap["total_put_call"] == 0.76
    assert snap["total_call_put"] == round(1 / 0.76, 3)
    by_key = {row["key"]: row for row in snap["buckets"]}
    assert by_key["index"]["volume_pct"] == 44.1
    assert by_key["equity"]["volume_pct"] == 35.3
    assert by_key["etp"]["volume_pct"] == 20.6
    assert by_key["equity"]["put_call"] == 0.58
    assert by_key["equity"]["call_put"] == round(1 / 0.58, 3)
    assert snap["source"] == "cboe"


def test_parse_escaped_next_payload() -> None:
    snap = parse_cboe_html(ESCAPED_HTML)
    assert snap["trade_date"] == "2026-09-04"
    assert snap["total_volume"] == 180
    assert snap["total_put_call"] == 0.76
    mix = {row["key"]: row["volume_pct"] for row in snap["buckets"]}
    assert mix["index"] == 50.0
    assert mix["equity"] == 33.3
    assert mix["etp"] == 16.7
