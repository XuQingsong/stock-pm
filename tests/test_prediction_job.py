from stock_pm.prediction import failed_prediction, synthesize_prediction
from stock_pm.prediction_job import publish_predictions_and_checks
from stock_pm.tape import synthesize_review_note, synthesize_tape_analysis


class _Store:
    def __init__(self):
        self.predictions = []
        self.checks = []
        self.jobs = []
        self.alerts = []
        self.states = []

    def market_session(self, as_of_date=None):
        return {
            "date": as_of_date or "2026-09-04",
            "is_trading_day": True,
            "default_review_date": as_of_date or "2026-09-04",
        }

    def active_symbols(self):
        return ["INTC"]

    def reviews_by_date(self, as_of_date):
        return [{"symbol": "INTC", "close_price": 20.0}]

    def history(self, symbol, limit, bar_size="1d"):
        return [
            {
                "symbol": symbol,
                "bar_time": "2026-09-04T20:00:00+00:00",
                "open_price": 20.1,
                "high_price": 20.4,
                "low_price": 19.8,
                "close_price": 20.0,
            }
        ]

    def latest_prediction(self, date, symbol, open_only=False):
        open_rows = [row for row in self.predictions if row.get("state") in {"auto_gen", "pending", "active"}]
        if open_only:
            return open_rows[-1] if open_rows else None
        if open_rows:
            return open_rows[-1]
        return self.predictions[-1] if self.predictions else None

    def prediction_checks(self, prediction_id):
        return [row for row in self.checks if row.get("prediction_id") == prediction_id]

    def build_live_prediction(self, symbol, date):
        env = {
            "one_liner": "盘面：缩量跌；消息：行业利多；因此：先按盘面读。",
            "synthesis": "盘面：缩量跌；消息：行业利多；因此：先按盘面读。",
            "publishState": "published",
            "struct": {"sentiment": {"atmosphere": "补涨"}},
            "prediction_ready": False,
        }
        tape = synthesize_tape_analysis(
            as_of_date=date,
            symbol=symbol,
            metrics={
                "day_change_pct": -1.2,
                "relative_volume": 0.6,
                "poc_60d": 19.5,
                "support": 19.0,
                "resistance": 22.0,
                "close": 20.0,
            },
            environment=env,
            source="test",
        )
        note = synthesize_review_note(
            as_of_date=date, symbol=symbol, tape=tape, environment=env, source="test"
        )
        return synthesize_prediction(
            as_of_date=date,
            symbol=symbol,
            environment=env,
            tape=tape,
            review_note=note,
            entry_price=20.0,
            support=19.0,
            resistance=22.0,
            source="job",
        )

    def append_prediction(self, pred):
        pred = dict(pred)
        pred["id"] = len(self.predictions) + 1
        self.predictions.append(pred)
        return pred

    def append_prediction_check(self, check):
        self.checks.append(check)

    def update_prediction_state(self, pred):
        self.states.append(pred)
        for row in self.predictions:
            if row.get("id") == pred.get("id"):
                row["state"] = pred.get("state")
                row["struct"] = pred.get("struct")

    def append_severity_alerts(self, alerts):
        self.alerts.extend(alerts)

    def append_job_run(self, job):
        self.jobs.append(job)


def test_job_appends_real_prediction_not_silent_empty() -> None:
    store = _Store()
    result = publish_predictions_and_checks(store, as_of_date="2026-09-04")
    assert result["status"] == "success"
    assert store.predictions[0]["prediction_ready"] is True
    assert store.predictions[0]["upside_bound_pct"] == 10.0
    assert store.predictions[0]["downside_bound_pct"] == -5.0
    assert store.jobs[0]["job_name"] == "prediction"


def test_job_checks_open_prediction_instead_of_stacking() -> None:
    store = _Store()
    first = publish_predictions_and_checks(store, as_of_date="2026-09-04")
    assert first["written"]
    second = publish_predictions_and_checks(store, as_of_date="2026-09-08")
    assert len(store.predictions) == 1
    assert second["checked"] == ["INTC"]
    assert store.checks
    assert store.predictions[0]["state"] == "active"


def test_job_failure_writes_visible_missing() -> None:
    store = _Store()

    def boom(symbol, date):
        raise RuntimeError("no bars")

    store.build_live_prediction = boom
    result = publish_predictions_and_checks(store, as_of_date="2026-09-04")
    assert result["status"] == "partial"
    assert store.predictions[0]["state"] == "missing"
    assert store.predictions[0]["prediction_ready"] is False
    assert failed_prediction("X", "2026-09-04", "x")["missing_label"]
