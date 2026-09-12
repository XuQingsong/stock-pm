from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from stock_pm.fetch import FetchError, json_get, read_cache, write_cache


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self._payload).encode()


def test_json_get_ok_and_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("stock_pm.fetch.urlopen", lambda *a, **k: _Resp({"ok": True}))
    # urlopen used with json.load(response) — need file-like
    class _JsonResp(_Resp):
        def __enter__(self):
            return self

        def __iter__(self):
            return iter([])

    def fake_urlopen(*args, **kwargs):
        class Handle:
            def __enter__(self_inner):
                return json.loads(json.dumps({"n": 1})) if False else self_inner

            def __exit__(self_inner, *a):
                return False

            def read(self_inner):
                return b'{"n": 1}'

        # json.load needs .read
        return Handle()

    # Patch json.load path: urlopen returns context manager whose file has read()
    import io

    def open_ok(*args, **kwargs):
        handle = io.BytesIO(b'{"n": 1}')
        handle.__enter__ = lambda: handle
        handle.__exit__ = lambda *a: False
        return handle

    monkeypatch.setattr("stock_pm.fetch.urlopen", open_ok)
    result = json_get("https://example.test/x", cache_key="demo", directory=tmp_path)
    assert result.status == "ok"
    assert result.from_cache is False
    assert result.payload == {"n": 1}
    assert "api_key" not in tmp_path.joinpath("demo.json").read_text()


def test_timeout_uses_cache(tmp_path, monkeypatch):
    write_cache("demo", {"n": 2}, tmp_path)

    def boom(*args, **kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr("stock_pm.fetch.urlopen", boom)
    result = json_get("https://example.test/x", cache_key="demo", directory=tmp_path, retries=1)
    assert result.from_cache is True
    assert result.status == "stale"
    assert result.payload == {"n": 2}


def test_429_without_cache_is_error(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise HTTPError("https://example.test/x", 429, "rate", hdrs=None, fp=None)

    monkeypatch.setattr("stock_pm.fetch.urlopen", boom)
    with pytest.raises(FetchError) as exc:
        json_get("https://example.test/x", cache_key="none", directory=tmp_path, retries=1)
    assert exc.value.reason_code == "rate_limited"
    assert "api_key" not in str(exc.value)


def test_429_uses_cache(tmp_path, monkeypatch):
    write_cache("demo", {"n": 3}, tmp_path)

    def boom(*args, **kwargs):
        raise HTTPError("https://example.test/x", 429, "rate", hdrs=None, fp=None)

    monkeypatch.setattr("stock_pm.fetch.urlopen", boom)
    result = json_get("https://example.test/x", cache_key="demo", directory=tmp_path, retries=1)
    assert result.from_cache is True
    assert result.status == "stale"
    assert result.reason_code == "record_stale"
    assert result.payload == {"n": 3}


def test_empty_cache_does_not_invent_values(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise URLError("timeout")

    monkeypatch.setattr("stock_pm.fetch.urlopen", boom)
    with pytest.raises(FetchError):
        json_get("https://example.test/x", cache_key="missing", directory=tmp_path, retries=1)
    assert read_cache("missing", tmp_path) is None
