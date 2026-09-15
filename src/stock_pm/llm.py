from __future__ import annotations

import hashlib
import json
import re
import time
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .analytics import VALID_BIASES
from .config import Settings

QUOTA_EXHAUSTED = "quota_exhausted"
RETRY_ON_REFRESH_STATUSES = frozenset({QUOTA_EXHAUSTED})
QUOTA_MARKERS = (
    "insufficient_quota",
    "insufficient_balance",
    "insufficient balance",
    "credit balance",
    "billing_not_active",
    "payment required",
    "payment_required",
    "exceeded your current quota",
    "quota exceeded",
    "余额不足",
    "账户余额",
    "欠费",
)
LLM_STATUS_HINTS = {
    "ok": "",
    "missing_key": "未配置 LLM_API_KEY，解释与明日看法未生成。",
    QUOTA_EXHAUSTED: "模型额度已用尽，请充值后刷新本页，将自动重新生成解释与明日看法。",
    "failed": "模型调用失败。可稍后刷新，或检查网络与 API 配置。",
}


SYSTEM_PROMPT = """你是美股自选复盘助手。只根据用户提供的 JSON 事实写作。
禁止编造未给出的价格、财报、新闻或宏观数据。若资料解释不了走势，必须明说。
输出且只输出一个 JSON 对象，字段为：
why: 今天为何这样走（中文，可引用提供的新闻标题与宏观，标明这是推断）
outlook: 明日大致看法（中文）
bias: 只能是 偏多、中性、偏空 之一
watch_low: 数字或 null
watch_high: 数字或 null
confidence: low、medium 或 high
"""


def _canonicalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _canonicalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        return round(float(value), 6)
    if isinstance(value, float):
        return round(value, 6)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def context_fingerprint(context: dict, *, model: str | None = None) -> str:
    payload = {"context": _canonicalize(context), "model": model or ""}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def reuse_llm_if_unchanged(
    context: dict,
    existing: dict | None,
    *,
    model: str | None = None,
    force: bool = False,
) -> tuple[str, dict | None]:
    fingerprint = context_fingerprint(context, model=model)
    if force or not existing:
        return fingerprint, None
    if existing.get("llm_context_hash") != fingerprint:
        return fingerprint, None
    if existing.get("llm_status") != "ok":
        return fingerprint, None
    if not (existing.get("llm_why") or existing.get("llm_outlook")):
        return fingerprint, None
    return fingerprint, {
        "llm_why": existing.get("llm_why"),
        "llm_outlook": existing.get("llm_outlook"),
        "llm_bias": existing.get("llm_bias"),
        "llm_model": existing.get("llm_model"),
        "llm_status": "ok",
        "llm_cached": True,
        "llm_generated_at": existing.get("llm_generated_at"),
        "llm_error": None,
        "confidence": existing.get("confidence"),
    }


class LLMRequestError(Exception):
    def __init__(self, status: int, body: str = "") -> None:
        self.status = status
        self.body = body or ""
        super().__init__(f"HTTP {status}: {self.body[:400]}")


def llm_status_message(status: str | None) -> str:
    return LLM_STATUS_HINTS.get(status or "failed") or LLM_STATUS_HINTS["failed"]


def classify_llm_error(status: int | None, body: str = "") -> str:
    text = (body or "").lower()
    if status == 402 or any(marker in text for marker in QUOTA_MARKERS):
        return QUOTA_EXHAUSTED
    return "failed"


def parse_llm_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError("model response is not JSON")
    payload = json.loads(match.group(0))
    bias = payload.get("bias")
    if bias not in VALID_BIASES:
        bias = "中性"
    confidence = payload.get("confidence")
    if confidence not in {"low", "medium", "high"}:
        confidence = "low"
    return {
        "why": (payload.get("why") or "").strip() or None,
        "outlook": (payload.get("outlook") or "").strip() or None,
        "bias": bias,
        "watch_low": payload.get("watch_low"),
        "watch_high": payload.get("watch_high"),
        "confidence": confidence,
    }


def _post_json(url: str, headers: dict[str, str], payload: dict, *, timeout: int = 60) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        error_body = ""
        try:
            error_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            error_body = ""
        raise LLMRequestError(exc.code, error_body) from exc


def _openai_usage(payload: dict) -> dict[str, int | None]:
    usage = payload.get("usage") or {}
    return {
        "input_tokens": usage.get("prompt_tokens"),
        "output_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
    }


def _anthropic_usage(payload: dict) -> dict[str, int | None]:
    usage = payload.get("usage") or {}
    inn = usage.get("input_tokens")
    out = usage.get("output_tokens")
    total = inn + out if inn is not None and out is not None else None
    return {"input_tokens": inn, "output_tokens": out, "total_tokens": total}


def _chat_openai_compatible(
    settings: Settings,
    system: str,
    user: str,
    *,
    timeout: int = 60,
    max_tokens: int | None = None,
    json_object: bool = False,
) -> tuple[str, str, dict[str, Any]]:
    base = (settings.llm_base_url or "https://api.openai.com/v1").rstrip("/")
    model = settings.llm_model or "gpt-4o-mini"
    body: dict[str, Any] = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if max_tokens:
        body["max_tokens"] = max_tokens
    if json_object:
        body["response_format"] = {"type": "json_object"}
    started = time.perf_counter()
    payload = _post_json(
        f"{base}/chat/completions",
        {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.llm_api_key}",
        },
        body,
        timeout=timeout,
    )
    latency_ms = int(round((time.perf_counter() - started) * 1000))
    text = (((payload.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
    used_model = payload.get("model") or model
    meta = {"latency_ms": latency_ms, **_openai_usage(payload)}
    return text, used_model, meta


def _chat_anthropic(
    settings: Settings,
    system: str,
    user: str,
    *,
    timeout: int = 60,
    max_tokens: int | None = None,
) -> tuple[str, str, dict[str, Any]]:
    model = settings.llm_model or "claude-3-5-haiku-latest"
    started = time.perf_counter()
    payload = _post_json(
        "https://api.anthropic.com/v1/messages",
        {
            "Content-Type": "application/json",
            "x-api-key": settings.llm_api_key,
            "anthropic-version": "2023-06-01",
        },
        {
            "model": model,
            "max_tokens": max_tokens or 2400,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
        timeout=timeout,
    )
    latency_ms = int(round((time.perf_counter() - started) * 1000))
    blocks = payload.get("content") or []
    text = "".join(block.get("text") or "" for block in blocks if isinstance(block, dict))
    meta = {"latency_ms": latency_ms, **_anthropic_usage(payload)}
    return text, model, meta


def _openai_complete(settings: Settings, context: dict) -> tuple[str, str]:
    text, model, _meta = _chat_openai_compatible(
        settings,
        SYSTEM_PROMPT,
        json.dumps(context, ensure_ascii=False, default=str),
    )
    return text, model


def _anthropic_complete(settings: Settings, context: dict) -> tuple[str, str]:
    text, model, _meta = _chat_anthropic(
        settings,
        SYSTEM_PROMPT,
        json.dumps(context, ensure_ascii=False, default=str),
    )
    return text, model


def parse_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    if start < 0:
        raise ValueError("model response is not JSON")
    try:
        payload, _end = json.JSONDecoder().raw_decode(raw[start:])
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError("model response is not JSON")
        payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise ValueError("model JSON must be an object")
    return payload


def _prompt_hash(system: str, user: str) -> str:
    encoded = (system or "") + "\n---\n" + (user or "")
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def complete_json(
    *,
    system: str,
    user: str,
    schema: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Provider-agnostic JSON completion for research agents. Never uses daily review prompts."""
    config = settings or Settings()
    provider = (config.llm_provider or "openai").strip().lower()
    model = config.llm_model or None
    prompt = user
    if schema:
        prompt = user + "\n\nReturn a single JSON object matching this schema:\n" + json.dumps(schema, ensure_ascii=False)
    digest = _prompt_hash(system, prompt)
    empty = {
        "status": "missing_key",
        "payload": None,
        "model": model,
        "provider": provider,
        "error": llm_status_message("missing_key"),
        "raw_text": None,
        "llm_called": False,
        "llm_status": "skipped",
        "prompt_hash": digest,
        "latency_ms": None,
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "fallback_used": True,
    }
    if not config.llm_api_key:
        return empty

    def _fail(status: str, error: str, *, used_model: str | None = None, meta: dict[str, Any] | None = None, raw_text: str | None = None) -> dict[str, Any]:
        hint = llm_status_message(status)
        detail = (error or "").strip()
        merged = hint if not detail else (detail if detail.startswith(hint) else f"{hint} {detail[:400]}")
        row = {
            **empty,
            "status": status,
            "llm_called": True,
            "llm_status": "failed",
            "error": merged,
            "model": used_model or model,
            "fallback_used": True,
            "raw_text": raw_text,
        }
        if meta:
            row["latency_ms"] = meta.get("latency_ms")
            row["input_tokens"] = meta.get("input_tokens")
            row["output_tokens"] = meta.get("output_tokens")
            row["total_tokens"] = meta.get("total_tokens")
        return row

    try:
        if provider == "anthropic":
            text, used_model, meta = _chat_anthropic(config, system, prompt, timeout=180, max_tokens=8192)
        else:
            try:
                text, used_model, meta = _chat_openai_compatible(
                    config,
                    system,
                    prompt,
                    timeout=180,
                    max_tokens=8192,
                    json_object=True,
                )
            except LLMRequestError as exc:
                if exc.status != 400:
                    raise
                text, used_model, meta = _chat_openai_compatible(
                    config,
                    system,
                    prompt,
                    timeout=180,
                    max_tokens=8192,
                    json_object=False,
                )
    except LLMRequestError as exc:
        status = classify_llm_error(exc.status, exc.body)
        return _fail(status, f"HTTP {exc.status}: {exc.body[:400]}")
    except (HTTPError, URLError, TimeoutError, KeyError) as exc:
        status = classify_llm_error(getattr(exc, "code", None), str(exc))
        return _fail(status, str(exc))
    try:
        return {
            "status": "ok",
            "payload": parse_json_object(text),
            "model": used_model,
            "provider": provider,
            "error": None,
            "raw_text": text,
            "llm_called": True,
            "llm_status": "ok",
            "prompt_hash": digest,
            "latency_ms": meta.get("latency_ms"),
            "input_tokens": meta.get("input_tokens"),
            "output_tokens": meta.get("output_tokens"),
            "total_tokens": meta.get("total_tokens"),
            "fallback_used": False,
        }
    except (ValueError, json.JSONDecodeError, KeyError) as exc:
        return _fail("failed", str(exc), used_model=used_model, meta=meta, raw_text=(text or "")[:800])


def complete_review(context: dict, settings: Settings | None = None) -> dict[str, Any]:
    config = settings or Settings()
    empty = {
        "llm_why": None,
        "llm_outlook": None,
        "llm_bias": None,
        "llm_model": None,
        "llm_status": "missing_key",
        "llm_error": llm_status_message("missing_key"),
        "confidence": None,
    }
    if not config.llm_api_key:
        return empty
    provider = (config.llm_provider or "openai").strip().lower()
    try:
        if provider == "anthropic":
            text, model = _anthropic_complete(config, context)
        else:
            text, model = _openai_complete(config, context)
        parsed = parse_llm_json(text)
        return {
            "llm_why": parsed["why"],
            "llm_outlook": parsed["outlook"],
            "llm_bias": parsed["bias"],
            "llm_model": model,
            "llm_status": "ok",
            "llm_error": None,
            "confidence": parsed["confidence"],
            "watch_low": parsed.get("watch_low"),
            "watch_high": parsed.get("watch_high"),
        }
    except LLMRequestError as exc:
        status = classify_llm_error(exc.status, exc.body)
        return {
            **empty,
            "llm_status": status,
            "llm_error": llm_status_message(status),
            "llm_model": config.llm_model or None,
            "error": str(exc),
        }
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError, KeyError) as exc:
        status = classify_llm_error(getattr(exc, "code", None), str(exc))
        return {
            **empty,
            "llm_status": status,
            "llm_error": llm_status_message(status),
            "llm_model": config.llm_model or None,
            "error": str(exc),
        }
