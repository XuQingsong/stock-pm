"""Hard deadlines for request-path event discovery.

The events job and the startup warm thread stay unbounded (they pass no
budget). Desk / API request paths install a budget so a hung official feed
cannot block a worker forever.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from contextlib import contextmanager
from typing import Callable, Iterator, TypeVar

# Desk overview budget: a few seconds per provider, ~5–8s overall.
PROVIDER_TIMEOUT_SECONDS = 4.0
OVERALL_TIMEOUT_SECONDS = 7.0
DESK_ASSEMBLE_TIMEOUT_SECONDS = 8.0
HTTP_TIMEOUT_CAP_SECONDS = 5.0
DEGRADED_COOLDOWN_SECONDS = 20.0

T = TypeVar("T")

_deadline: float | None = None
_provider_timeout: float | None = None
_state_lock = threading.Lock()
_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="events-budget")


class BudgetTimeout(TimeoutError):
    """Discovery or feed fetch exceeded the request-path budget."""


def request_budget_active() -> bool:
    return _deadline is not None


def remaining_seconds() -> float | None:
    deadline = _deadline
    if deadline is None:
        return None
    return deadline - time.monotonic()


def budget_exhausted() -> bool:
    left = remaining_seconds()
    return left is not None and left <= 0


def provider_timeout_seconds() -> float | None:
    if _deadline is None and _provider_timeout is None:
        return None
    cap = _provider_timeout if _provider_timeout is not None else PROVIDER_TIMEOUT_SECONDS
    left = remaining_seconds()
    if left is None:
        return cap
    return max(0.0, min(cap, left))


def capped_timeout(requested: float, *, cap: float = HTTP_TIMEOUT_CAP_SECONDS) -> float:
    """Shrink an HTTP timeout to the remaining request budget."""
    timeout = float(requested)
    left = remaining_seconds()
    if left is None:
        return timeout
    timeout = min(timeout, cap, max(0.05, left))
    return timeout


@contextmanager
def discovery_budget(
    *,
    overall: float | None = None,
    provider: float | None = None,
) -> Iterator[None]:
    """Install a process-wide request budget. Nested calls inherit the outer one."""
    global _deadline, _provider_timeout
    if _deadline is not None:
        yield
        return
    overall_s = OVERALL_TIMEOUT_SECONDS if overall is None else overall
    provider_s = PROVIDER_TIMEOUT_SECONDS if provider is None else provider
    with _state_lock:
        prev_deadline = _deadline
        prev_provider = _provider_timeout
        _deadline = time.monotonic() + max(0.05, overall_s)
        _provider_timeout = provider_s
    try:
        yield
    finally:
        with _state_lock:
            _deadline = prev_deadline
            _provider_timeout = prev_provider


def call_with_timeout(fn: Callable[[], T], timeout: float) -> T:
    """Run *fn* in a worker thread; raise BudgetTimeout if it exceeds *timeout*."""
    if timeout <= 0 or budget_exhausted():
        raise BudgetTimeout("deadline_exceeded")
    future = _POOL.submit(fn)
    try:
        return future.result(timeout=timeout)
    except FuturesTimeout as exc:
        raise BudgetTimeout("timeout") from exc
