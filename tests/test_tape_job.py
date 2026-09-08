from stock_pm.tape import TAPE_MISSING_LINE, failed_tape
from stock_pm.tape_job import publish_tape_and_reviews


class MemoryStore:
    def __init__(self, *, fail_symbols=None, fail_append=None):
        self.fail_symbols = set(fail_symbols or [])
        self.fail_append = set(fail_append or [])
        self.tapes: list[dict] = []
        self.notes: list[dict] = []
        self.jobs: list[dict] = []

    def market_session(self, trade_date=None):
        return {
            "date": trade_date or "2026-09-04",
            "is_trading_day": True,
            "default_review_date": "2026-09-04",
        }

    def active_symbols(self):
        return ["NVDA", "INTC"]

    def build_live_tape(self, symbol, as_of_date=None, **kwargs):
        if symbol in self.fail_symbols:
            raise RuntimeError("bars exploded")
        return {
            "as_of_date": as_of_date,
            "symbol": symbol,
            "one_liner": f"{symbol} 放量跌，续杀",
            "conclusion": f"{symbol} 放量跌",
            "struct": {"volume_price": {"form": "放量跌"}},
            "missingFlags": [],
            "publishState": "published",
            "prediction_ready": False,
        }

    def build_live_review_note(self, symbol, as_of_date=None, tape=None, **kwargs):
        return {
            "as_of_date": as_of_date,
            "symbol": symbol,
            "summary": f"昨天{symbol}放量跌。",
            "explanation": "环境：承压。昨盘：放量跌。因此：逃跑（推断）。",
            "unexplained": False,
            "missingFlags": [],
            "publishState": "published",
        }

    def append_tape_analysis(self, snapshot):
        symbol = snapshot.get("symbol")
        if symbol in self.fail_append:
            raise RuntimeError("write failed")
        self.tapes.append(snapshot)

    def append_review_note(self, note):
        self.notes.append(note)

    def append_job_run(self, job):
        self.jobs.append(job)


def test_publish_appends_tape_and_note_per_symbol() -> None:
    store = MemoryStore()
    result = publish_tape_and_reviews(store, as_of_date="2026-09-04")
    assert result["status"] == "success"
    assert {row["symbol"] for row in store.tapes} == {"NVDA", "INTC"}
    assert {row["symbol"] for row in store.notes} == {"NVDA", "INTC"}
    assert store.jobs[-1]["job_name"] == "tape"
    assert store.jobs[-1]["status"] == "success"
    assert all(row.get("publishState") != "missing" for row in store.tapes)


def test_publish_failure_writes_visible_missing_not_silence() -> None:
    store = MemoryStore(fail_symbols={"INTC"})
    result = publish_tape_and_reviews(store, as_of_date="2026-09-04")
    assert result["status"] == "partial"
    intc = next(row for row in store.tapes if row.get("symbol") == "INTC")
    assert intc["publishState"] == "missing"
    assert TAPE_MISSING_LINE in intc["one_liner"]
    assert intc["volume_price"] is None or intc.get("struct", {}).get("volume_price") is None
    assert store.jobs[-1]["status"] == "partial"
    assert "INTC" in (store.jobs[-1]["error"] or "")


def test_failed_tape_helper_matches_job_contract() -> None:
    snap = failed_tape("MU", "2026-09-04", "disk full")
    assert snap["missingFlags"]
    assert snap["publishState"] == "missing"
    assert snap["prediction_ready"] is False
