"""Fixed Event Impact fixtures. Sourced from existing Brain materials, no new search."""

from __future__ import annotations

from typing import Any


def _event(
    event_id: str,
    *,
    title: str,
    date: str,
    summary: str,
    source: str,
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "title": title,
        "date": date,
        "summary": summary,
        "source": source,
    }


EVENTS: dict[str, list[dict[str, Any]]] = {
    "AAPL": [
        _event("aapl_e1", title="Q3 FY2026 earnings: June-quarter records", date="2026-07-30", summary="Apple 8-K EX-99.1: June quarter records for total company revenue and EPS; iPhone, Mac and Services revenue set new June quarter records.", source="sec.exhibit"),
        _event("aapl_e2", title="Q2 FY2026 earnings: Services all-time high", date="2026-04-30", summary="Apple 8-K EX-99.1: March quarter records for total company revenue, iPhone revenue, and EPS; Services revenue reaches new all-time high.", source="sec.exhibit"),
        _event("aapl_e3", title="iPhone Duo foldable launch", date="2026-09-09", summary="Apple introduced iPhone Duo, first foldable iPhone, 7.6-inch inner / 5.4-inch outer display, priced at $1,999 in independent coverage.", source="apple.com / independent_media"),
        _event("aapl_e4", title="Siri AI / Apple Intelligence rollout", date="2026-09-14", summary="Next-generation Apple Intelligence powering Siri AI started rolling out across iOS 27, iPadOS 27, and macOS 27.", source="apple.com"),
        _event("aapl_e5", title="One-time tariff refund in gross margin", date="2026-07-30", summary="Claim material: latest-quarter gross margin allegedly includes a favorable one-time tariff refund. Excerpt of the 8-K in the frozen set does not state the refund.", source="existing Core Claim / missing in excerpt"),
        _event("aapl_e6", title="Product supply constraints", date="2026-07-30", summary="Candidate claim that management cited supply constraints that may have capped reported hardware revenue. Not confirmed in frozen 8-K excerpts.", source="existing candidate claim"),
        _event("aapl_e7", title="App Store / DMA regulatory pressure", date="2026-09-01", summary="Counter-research question already on the Services claim: DMA / App Store economics could compress Services mix or take-rate.", source="existing counter_research_questions"),
        _event("aapl_e8", title="India-to-US iPhone airfreight", date="2026-09-01", summary="Evidence in a prior Brain run: Apple chartering freighters to move iPhones from India to the US, possibly tariff or supply-chain related.", source="existing evidence set"),
        _event("aapl_e9", title="Post-earnings market reaction", date="2026-07-31", summary="Candidate not selected as core: post-earnings sell-off as a signal of skepticism on growth quality despite record prints.", source="existing why_not_core candidate"),
        _event("aapl_e10", title="Valuation multiple vs margin normalization", date="2026-07-30", summary="Existing Core Claim: TTM PE may compress if a non-recurring margin benefit reverses. The 37.95 multiple was not verified in evidence.", source="existing Core Claim"),
    ],
    "AVGO": [
        _event("avgo_e1", title="Q3 FY2026 results: AI accelerators very strong", date="2026-09-04", summary="Broadcom Q3 FY2026 earnings release: AI accelerators and networking continues to be very strong. No $21.7B / +236% in the frozen excerpts used for the final claim.", source="sec.exhibit"),
        _event("avgo_e2", title="Third-party: AI semiconductor revenue doubling", date="2026-09-01", summary="Aggregator analysis in the frozen set: Broadcom has secured supply to double AI semiconductor revenue in each of the next two years, naming Anthropic and OpenAI demand.", source="aggregator in evidence set"),
        _event("avgo_e3", title="Google taps Marvell for custom silicon", date="2026-09-01", summary="Counter evidence already linked: Google engaged Marvell for custom silicon attaching to the TPU ecosystem, including AI inference accelerators.", source="existing oppose link"),
        _event("avgo_e4", title="Meta MTIA 450 in-house AI chip deployment", date="2026-09-01", summary="Independent coverage: Meta plans to deploy third-generation in-house AI chip MTIA 450 (Arke) in data centers in 1H next year.", source="independent_media oppose link"),
        _event("avgo_e5", title="Meta MTIA 400 generative AI accelerator", date="2026-09-01", summary="Meta detailed MTIA 400 aimed at LLM training, additional in-house silicon evidence.", source="existing oppose/contextual link"),
        _event("avgo_e6", title="VMware infrastructure software margins", date="2026-09-04", summary="Aggregator fact in the frozen set: infrastructure software / VMware at 93% gross and 79% operating margin.", source="aggregator"),
        _event("avgo_e7", title="Private credit SPVs and packaging integration", date="2026-09-01", summary="Evidence that Broadcom is using private credit SPVs and vertical integration into advanced packaging substrates to de-risk custom AI accelerator growth.", source="existing contextual evidence"),
        _event("avgo_e8", title="Debt tender offer", date="2026-06-01", summary="Issuer announcement of pricing terms for debt tender offers. Unrelated to AI demand unless the model over-routes it.", source="issuer 8-K"),
        _event("avgo_e9", title="EPS execution vs revenue strength", date="2026-09-04", summary="Existing Core Claim: earnings execution may be inconsistent even as AI revenue is described as strong. Specific EPS miss figures were not in the excerpt.", source="existing Core Claim"),
        _event("avgo_e10", title="Reported holder selling Broadcom", date="2026-09-01", summary="News hit already retrieved in Brain news: a well-known holder dumped Broadcom while raising another large-cap position. Not an issuer operating fact.", source="existing news_interpretation corpus"),
    ],
    "LITE": [
        _event("lite_e1", title="Q4 FY2026 print: $1.01B revenue, GM 47.4%", date="2026-08-01", summary="Issuer 8-K: Q4 FY2026 net revenue $1.01 billion, GAAP gross margin 47.4%, non-GAAP 50.4%.", source="sec.exhibit"),
        _event("lite_e2", title="Q3 FY2026 print: $808.4M revenue, GM 44.2%", date="2026-05-01", summary="Issuer 8-K: Q3 FY2026 net revenue $808.4 million, GAAP gross margin 44.2%, non-GAAP 47.9%.", source="sec.exhibit"),
        _event("lite_e3", title="Q1 FY2027 revenue guidance $1.225B–$1.275B", date="2026-08-01", summary="Management guidance in the Q4 materials: Q1 FY2027 revenue $1.225–$1.275B.", source="sec.exhibit / guidance"),
        _event("lite_e4", title="Datacom mix and manufacturing utilization", date="2026-08-01", summary="Existing Core Claim: sequential margin expansion attributed to utilization and Datacom laser mix, without segment GM proof.", source="existing Core Claim"),
        _event("lite_e5", title="Optical inventory / pricing pressure", date="2026-09-01", summary="Counter-search query already executed: optical inventory build or pricing pressure that could make the ramp cyclical.", source="existing counter_queries"),
        _event("lite_e6", title="Peer capacity: Coherent / Fabrinet", date="2026-09-01", summary="Counter-search query: peer capacity expansion at Coherent or Fabrinet, industry_peer / related_entity check on optical demand.", source="existing counter_queries"),
        _event("lite_e7", title="CPO technology displacement", date="2026-09-01", summary="Counter-search query: CPO displacement risk to transceiver / laser demand durability.", source="existing counter_queries"),
        _event("lite_e8", title="Earnings-day stock volatility", date="2026-08-01", summary="Existing candidate/claim: large stock moves on small EPS beats/misses, high execution sensitivity. Price-reaction evidence was missing.", source="existing Core Claim"),
        _event("lite_e9", title="Customer concentration undisclosed", date="2026-08-01", summary="Candidate not selected as core: customer concentration risk is unknown but potentially material; missing top-customer %.", source="existing why_not_core"),
        _event("lite_e10", title="Stale 2023 83% YoY growth print", date="2023-12-31", summary="Secondary snippet in the frozen set: total revenue +83.22% YoY and +24.48% QoQ in 2023. A routing test: should be background / not current operating.", source="existing weak/unknown evidence"),
    ],
}


def events_for(ticker: str) -> list[dict[str, Any]]:
    return list(EVENTS.get(str(ticker or "").upper()) or [])
