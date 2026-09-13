from stock_pm.config import DEFAULT_DATABASE_URL, database_url_from_env, redact_database_url


def test_redact_database_url_never_keeps_password():
    raw = "postgresql://stock_pm:super-secret@db.internal:5432/stock_pm"
    redacted = redact_database_url(raw)
    assert "super-secret" not in redacted
    assert "stock_pm:***@db.internal:5432/stock_pm" in redacted


def test_database_url_from_env_uses_process_env_only(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert database_url_from_env() == DEFAULT_DATABASE_URL
    monkeypatch.setenv("DATABASE_URL", "postgresql://app:hidden@127.0.0.1:5432/app")
    assert database_url_from_env() == "postgresql://app:hidden@127.0.0.1:5432/app"
    assert "hidden" not in redact_database_url(database_url_from_env())
