from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv


load_dotenv()
load_dotenv(".env.server")

# Documented local-dev default only. Production must set DATABASE_URL from env
# or a gitignored file. Never commit real passwords.
DEFAULT_DATABASE_URL = "postgresql://stock_pm:stock_pm_dev@localhost:5432/stock_pm"


def database_url_from_env(*, default: str = DEFAULT_DATABASE_URL) -> str:
    """Read DATABASE_URL from the process environment only."""
    raw = os.getenv("DATABASE_URL")
    if raw is None:
        return default
    return raw.strip() or default


def redact_database_url(url: str) -> str:
    """Return a log-safe DSN with the password removed."""
    parts = urlsplit(url)
    if not parts.scheme or not parts.hostname:
        return "<invalid-database-url>"
    user = parts.username or ""
    host = parts.hostname
    port = f":{parts.port}" if parts.port else ""
    auth = f"{user}:***@" if user else ("***@" if parts.password else "")
    netloc = f"{auth}{host}{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def database_url_is_explicit() -> bool:
    return bool((os.getenv("DATABASE_URL") or "").strip())


@dataclass(frozen=True, slots=True)
class Instrument:
    symbol: str
    primary_exchange: str
    name: str
    asset_class: str = "stocks"
    sector: str | None = None
    themes: tuple[str, ...] = ()
    rate_sensitivity: str = "medium"


# Seed rows for the watchlist table. The database is the source of truth at
# runtime; this list is only inserted on first initialization (ON CONFLICT
# DO NOTHING) so new deployments start with a sensible watchlist.
DEFAULT_WATCHLIST: dict[str, Instrument] = {
    "MU": Instrument("MU", "NASDAQ", "Micron Technology Inc", "stocks",
                     "半导体", ("semis", "high_valuation_growth"), "high"),
    "INTC": Instrument("INTC", "NASDAQ", "Intel Corp", "stocks",
                       "半导体", ("semis",), "medium"),
    "AAPL": Instrument("AAPL", "NASDAQ", "Apple Inc", "stocks",
                       "消费电子", ("consumer_electronics",), "medium"),
    "GOOGL": Instrument("GOOGL", "NASDAQ", "Alphabet Inc Class A", "stocks",
                        "互联网", ("high_valuation_growth",), "high"),
    "NVDA": Instrument("NVDA", "NASDAQ", "NVIDIA Corp", "stocks",
                       "半导体", ("semis", "high_valuation_growth"), "high"),
    "SKHY": Instrument("SKHY", "NASDAQ", "SK Hynix Inc ADR", "stocks",
                       "半导体", ("semis", "high_valuation_growth"), "high"),
    "NOK": Instrument("NOK", "NYSE", "Nokia Corp ADR", "stocks",
                      "通信设备", ("telecom",), "low"),
    "XOM": Instrument("XOM", "NYSE", "Exxon Mobil Corp", "stocks",
                      "能源", ("energy", "oil_producer"), "low"),
    "JPM": Instrument("JPM", "NYSE", "JPMorgan Chase & Co", "stocks",
                      "银行", ("banks", "credit"), "medium"),
    "AVGO": Instrument("AVGO", "NASDAQ", "Broadcom Inc", "stocks",
                       "半导体", ("semis", "high_valuation_growth"), "high"),
    "QQQ": Instrument("QQQ", "NASDAQ", "Invesco QQQ Trust Series 1", "etf",
                      "指数ETF", ("index", "high_valuation_growth"), "high"),
}


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str = field(default_factory=database_url_from_env)
    database_pool_size: int = field(default_factory=lambda: int(os.getenv("DATABASE_POOL_SIZE", "5")))
    alpaca_api_key_id: str = field(default_factory=lambda: os.getenv("ALPACA_API_KEY_ID", ""))
    alpaca_api_secret_key: str = field(default_factory=lambda: os.getenv("ALPACA_API_SECRET_KEY", ""))
    alpaca_data_feed: str = field(default_factory=lambda: os.getenv("ALPACA_DATA_FEED", "iex"))
    alpaca_bars_feed: str = field(default_factory=lambda: os.getenv("ALPACA_BARS_FEED", "sip"))
    alpaca_options_feed: str = field(default_factory=lambda: os.getenv("ALPACA_OPTIONS_FEED", "indicative"))
    fred_api_key: str = field(default_factory=lambda: os.getenv("FRED_API_KEY", ""))
    fmp_api_key: str = field(default_factory=lambda: os.getenv("FMP_API_KEY", ""))
    alpha_vantage_api_key: str = field(default_factory=lambda: os.getenv("ALPHA_VANTAGE_API_KEY", ""))
    llm_api_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", ""))
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "openai"))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "deepseek-chat"))
    llm_base_url: str = field(default_factory=lambda: os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1"))
    llm_timeout_seconds: int = field(default_factory=lambda: int(os.getenv("LLM_TIMEOUT_SECONDS", "180")))
    llm_max_tokens: int = field(default_factory=lambda: int(os.getenv("LLM_MAX_TOKENS", "8192")))
    llm_extra_body: dict | None = field(default=None)
    strong_model_provider: str = field(default_factory=lambda: os.getenv("STRONG_MODEL_PROVIDER", "").strip())
    strong_model_api_key: str = field(default_factory=lambda: os.getenv("STRONG_MODEL_API_KEY", "").strip())
    strong_model_base_url: str = field(default_factory=lambda: os.getenv("STRONG_MODEL_BASE_URL", "").strip())
    strong_model_name: str = field(default_factory=lambda: os.getenv("STRONG_MODEL_NAME", "").strip())
    dashscope_api_key: str = field(default_factory=lambda: os.getenv("DASHSCOPE_API_KEY", "").strip())
    mechanical_model_provider: str = field(default_factory=lambda: os.getenv("MECHANICAL_MODEL_PROVIDER", "").strip())
    mechanical_model_name: str = field(default_factory=lambda: os.getenv("MECHANICAL_MODEL_NAME", "").strip())
    mechanical_model_api_key: str = field(default_factory=lambda: os.getenv("MECHANICAL_MODEL_API_KEY", "").strip())
    mechanical_model_base_url: str = field(default_factory=lambda: os.getenv("MECHANICAL_MODEL_BASE_URL", "").strip())
    reasoning_model_provider: str = field(default_factory=lambda: os.getenv("REASONING_MODEL_PROVIDER", "").strip())
    reasoning_model_name: str = field(default_factory=lambda: os.getenv("REASONING_MODEL_NAME", "").strip())
    reasoning_model_api_key: str = field(default_factory=lambda: os.getenv("REASONING_MODEL_API_KEY", "").strip())
    reasoning_model_base_url: str = field(default_factory=lambda: os.getenv("REASONING_MODEL_BASE_URL", "").strip())
    benchmark_models: str = field(default_factory=lambda: os.getenv("BENCHMARK_MODELS", "").strip())
    large_trade_notional: float = field(default_factory=lambda: float(os.getenv("LARGE_TRADE_NOTIONAL", "200000")))
    app_env: str = field(default_factory=lambda: (os.getenv("APP_ENV") or "").strip().lower())
    enable_decision_preview: bool = field(
        default_factory=lambda: (os.getenv("ENABLE_DECISION_PREVIEW") or "").strip().lower()
        in {"1", "true", "yes", "on"}
    )
    enable_decision_inject: bool = field(
        default_factory=lambda: (os.getenv("ENABLE_DECISION_INJECT") or "").strip().lower()
        in {"1", "true", "yes", "on"}
    )
    google_cse_api_key: str = field(default_factory=lambda: os.getenv("GOOGLE_CSE_API_KEY", ""))
    google_cse_id: str = field(default_factory=lambda: os.getenv("GOOGLE_CSE_ID", ""))
    tavily_api_key: str = field(default_factory=lambda: os.getenv("TAVILY_API_KEY", "").strip())
    exa_api_key: str = field(default_factory=lambda: os.getenv("EXA_API_KEY", "").strip())
    events_mode: str = field(
        default_factory=lambda: (os.getenv("STOCK_PM_EVENTS_MODE") or "").strip().lower()
    )
    # SEC EDGAR fair-access User-Agent. Empty means not configured; reserved hosts are rejected.
    sec_edgar_user_agent: str = field(
        default_factory=lambda: (os.getenv("SEC_EDGAR_USER_AGENT") or "").strip()
    )
    # Max Alpha Vantage earnings HTTP calls per discover. Do not raise concurrency to beat limits.
    earnings_av_budget: int = field(
        default_factory=lambda: max(1, int(os.getenv("STOCK_PM_EARNINGS_BUDGET") or "8"))
    )
