"""Chinese presentation copy for the research review page. No ticker branches."""

from __future__ import annotations

from typing import Any

from .extract import to_number


LAYER_ZH = {
    "customer_demand": "客户需求",
    "customer_capex": "客户资本开支",
    "site_power": "数据中心 / 电力",
    "product_deployments": "部署",
    "networking": "网络",
    "foundry_packaging": "供应链",
    "issuer_revenue": "公司收入",
    "commodity_price": "商品价格",
    "production_volume": "产量",
    "project_capex": "项目资本开支",
    "cash_generation": "现金创造",
    "end_demand": "终端需求",
    "conversion": "转化",
    "supply": "供给",
}

FAMILY_ZH = {
    "growth_end_market": "AI / 终端需求增长",
    "core_product": "核心半导体业务",
    "software_recurring": "软件经常性收入",
    "networking": "网络",
    "production_volume": "产量",
    "commodity_price": "商品价格",
    "unknown / missing": "未知 / 缺失",
}

STATUS_ZH = {
    "strengthened": "已加强",
    "weakened": "已削弱",
    "broken": "已失效",
    "unchanged": "未改判",
    "unverified": "待验证",
    "promised": "已承诺",
    "externally_noted": "外部记录",
    "beat": "超预期",
    "met": "符合预期",
    "miss": "低于预期",
    "missed": "低于预期",
    "revised": "已下调/上修",
    "unscored": "未评分",
    "provisional": "暂估",
    "missing": "缺失",
    "core": "核心",
    "supporting": "支持",
    "monitoring": "跟踪",
    "high": "强",
    "medium": "中",
    "low": "弱",
}

ORIGIN_ZH = {
    "management_guidance": "管理层指引",
    "market_implied_under_base_multiple": "在基准估值倍数下反推",
    "market_implied": "市场隐含",
    "official_materials": "公司官方材料",
    "independent_customer": "独立客户来源",
    "industry_demand_only": "仅支持行业需求",
    "issuer_management": "公司管理层",
    "industry_third_party": "行业第三方",
    "estimated": "估算",
    "top_down_range": "自上而下区间",
}

BRANCH_ZH = {
    "Demand": "需求",
    "Execution": "执行",
    "Economics": "经济性",
    "Market": "市场",
    "Other": "其他",
}

MISSING_ZH = {
    "investment thesis": "投资逻辑",
    "valuation": "估值",
    "FCF": "自由现金流",
    "fcf": "自由现金流",
    "FCF missing": "缺少自由现金流",
    "official segment mix missing": "缺少官方分部结构",
    "official segment mix": "官方分部结构",
    "independent customer contract confirmation": "独立客户合同确认",
    "scored delivery sample shorter than 6 quarters": "可评分兑现样本不足 6 季",
    "segment growth": "分部增长",
    "segment mix": "分部结构",
    "net margin": "净利率",
    "diluted shares": "摊薄股本",
}


def zh_status(value: Any) -> str:
    key = str(value or "").strip()
    return STATUS_ZH.get(key, STATUS_ZH.get(key.lower(), key or "待验证"))


def zh_origin(value: Any) -> str:
    key = str(value or "").strip()
    return ORIGIN_ZH.get(key, key.replace("_", " ") if key else "尚未标注")


def zh_layer(value: Any, ticker: str | None = None) -> str:
    key = str(value or "").strip()
    if key == "issuer_revenue" and ticker:
        return f"{ticker}收入"
    return LAYER_ZH.get(key, key.replace("_", " ") if key else "未标注")


def _horizon_zh(value: Any) -> str:
    key = str(value or "").lower()
    mapping = {
        "multi_year": "多年",
        "fy": "财年",
        "next_print": "下次财报",
        "unspecified": "未标明",
    }
    return mapping.get(key, str(value or "未标明"))


def _metric_zh(value: Any) -> str:
    key = str(value or "").strip()
    mapping = {
        "growth_end_market": "AI / 终端需求增长",
        "software": "软件经常性收入",
        "contract": "合同",
        "unspecified": "未标明",
        "fy": "财年",
        "revenue": "收入",
        "eps": "每股收益",
        "margin": "利润率",
    }
    return mapping.get(key, FAMILY_ZH.get(key, key.replace("_", " ") if key else "未标明"))


def zh_family(value: Any) -> str:
    key = str(value or "").strip()
    return FAMILY_ZH.get(key, key.replace("_", " ") if key else "来源未明")


def zh_missing(value: Any) -> str:
    key = str(value or "").strip()
    return MISSING_ZH.get(key, key.replace("_", " "))


def zh_gap(value: Any) -> str:
    text = str(value or "").strip()
    low = text.lower()
    if not text or text in {"Missing", "unresolved"}:
        return "尚未形成可验证结论"
    if "next official print" in low or "stated claim" in low or "stated outlook" in low:
        return "下次财报对照承诺"
    if "scored sample" in low or "prints_scored" in low or "6–8" in low or "6-8" in low:
        return "可评分兑现样本仍不足 6 季"
    if "reported margin" in low:
        return "已有利润率背景，结构仍待拆开"
    if "customer concentration" in low:
        return "客户集中度仍构成久期约束"
    if "slippage on the weakest" in low:
        return "最弱兑现环节继续恶化"
    if "cancellation" in low or "guidance cut" in low:
        return "核心交付承诺被取消或指引下修"
    if "independent customer confirmation" in low and "capex" in low:
        return "独立客户确认资本开支与部署按期转化"
    if "independent customer" in low or ("named" in low and "contract" in low):
        return "独立客户资本开支与具名合同仍未确认"
    if "scored delivery" in low or "6 quarter" in low:
        return "可评分兑现样本不足 6 季，不能当作长期可信度"
    if "guidance delivery" in low:
        return "指引兑现仍需对照后续财报"
    if "industry demand hits" in low:
        return "行业需求证据不能替代该公司具名合同确认"
    if "fcf" in low:
        return "缺少自由现金流"
    if "segment" in low:
        return "缺少官方分部结构"
    if "未发现足够反证" in text:
        return "反证仍不足"
    if any(ord(ch) > 127 for ch in text):
        return text[:80]
    return "待进一步验证"


def _band(confidence: Any) -> str:
    number = to_number(confidence)
    if number is None:
        return "未知"
    if number >= 0.7:
        return "较高"
    if number >= 0.45:
        return "中等"
    return "偏低"


def _strength(confidence: Any, weakest: bool = False, bottleneck: bool = False) -> str:
    if weakest or bottleneck:
        return "弱"
    key = str(confidence or "").lower()
    if key in {"high", "medium", "low"}:
        return STATUS_ZH[key]
    number = to_number(confidence)
    if number is None:
        return "中"
    if number >= 0.7:
        return "强"
    if number >= 0.4:
        return "中"
    return "弱"


def _clip(value: Any, limit: int = 72) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip("，,;； ") + "…"


def _growth(case: dict[str, Any], *, implied_range: str | None = None) -> str:
    if implied_range:
        return str(implied_range).replace("~", "").replace(" ", "")
    rate = to_number(case.get("growth"))
    if rate is not None:
        return f"{int(round(float(rate) * 100))}%"
    display = case.get("growth_display")
    if display:
        return str(display).replace("~", "")
    return "待补"


def _money_target(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text in {"Missing", "None"}:
        return "待补"
    return text.replace("~", "")


def _ledger_bucket(status: str) -> str:
    key = str(status or "").lower()
    if key in {"beat", "met", "delivered", "kept"}:
        return "delivered"
    if key in {"delayed", "slipped"}:
        return "delayed"
    if key in {"broken", "cancelled", "missed", "miss"}:
        return "broken"
    return "pending"


def _assumption_hay(row: dict[str, Any]) -> str:
    return " ".join(
        str(row.get(key) or "")
        for key in ("statement", "kind", "thesis_role", "title")
    ).lower()


def _flatten_nodes(tree: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for branch in tree.get("branches") or []:
        for node in branch.get("nodes") or []:
            item = dict(node)
            item["branch"] = branch.get("title")
            out.append(item)
    return out


def _key_assumptions(tree: dict[str, Any], golden: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = _flatten_nodes(tree)
    by_id = {str(row.get("assumption_id") or ""): row for row in nodes}
    for row in golden.get("top_assumptions") or []:
        aid = str(row.get("assumption_id") or "")
        if aid and aid in by_id:
            by_id[aid] = {**by_id[aid], **row}
        elif row.get("statement"):
            nodes.append(row)
    slots = [
        ("合同是否兑现", ("contract", "commitment", "deliver the stated", "guidance")),
        ("客户部署是否落地", ("capex", "customer", "deploy", "accelerator", "capacity")),
        ("两年增长是否持续", ("persist", "growth", "two year", "2y")),
    ]
    used: set[str] = set()
    picked: list[dict[str, Any]] = []
    for title, tokens in slots:
        match = None
        for row in nodes:
            aid = str(row.get("assumption_id") or row.get("statement") or "")
            if aid in used:
                continue
            hay = _assumption_hay(row)
            if any(token in hay for token in tokens):
                match = row
                break
        if match is None:
            for row in nodes:
                aid = str(row.get("assumption_id") or row.get("statement") or "")
                if aid not in used:
                    match = row
                    break
        if not match:
            picked.append(
                {
                    "title": title,
                    "status": "unverified",
                    "status_label": "待验证",
                    "confidence": None,
                    "support": "支持：尚未形成可追溯证据",
                    "risk": "风险：该假设仍待验证",
                    "node": None,
                }
            )
            continue
        used.add(str(match.get("assumption_id") or match.get("statement") or ""))
        support_rows = match.get("supporting") or []
        unresolved = match.get("unresolved") or []
        if "合同" in title:
            support = "支持：官方材料中有多年合同与收入确认安排" if support_rows else "支持：尚未形成可追溯证据"
            risk = "风险：客户未具名，仍缺独立验证"
        elif "部署" in title:
            support = "支持：有客户部署/产能相关官方表述" if support_rows else "支持：尚未形成可追溯证据"
            risk = "风险：独立客户资本开支仍未确认"
        else:
            support = "支持：近期增长证据存在，但持续性未锁定" if support_rows else "支持：尚未形成可追溯证据"
            risk = f"风险：{zh_gap(unresolved[0] if unresolved else '增长可能无法持续')}"
        picked.append(
            {
                "title": title,
                "statement": match.get("statement"),
                "status": match.get("status") or match.get("final_status") or "unverified",
                "status_label": zh_status(match.get("status") or match.get("final_status") or "unverified"),
                "confidence": match.get("confidence") or match.get("final_confidence"),
                "support": support,
                "risk": risk,
                "node": match,
            }
        )
    return picked


def _monitor_zh(row: dict[str, Any], weakest_zh: str) -> dict[str, Any]:
    hay = str(row.get("item") or "").lower()
    if "print" in hay or "outlook" in hay:
        item = "下一次财报是否兑现指引"
        nxt = "下次财报"
    elif "customer capex" in hay or "deployment" in hay or "independent customer" in hay:
        item = "客户资本开支 / 部署"
        nxt = "客户公开文件与部署进展"
    elif "weakest" in hay or "chain layer" in hay:
        item = f"需求兑现链条最弱环节（{weakest_zh}）"
        nxt = f"复查{weakest_zh}"
    elif "margin" in hay or "mix" in hay:
        item = "利润率与业务结构"
        nxt = "净利率 / 经营利润率与结构"
    elif "concentration" in hay:
        item = "客户集中度"
        nxt = "收入占比是否重述"
    else:
        item = _clip(row.get("item"), 28) or "跟踪项"
        nxt = "下次官方更新"
    swing = "增强：独立验证落地；削弱：兑现或部署低于承诺"
    return {
        "item": item,
        "current_state": _clip(zh_gap(row.get("current_state")), 36) if row.get("current_state") else "待观察",
        "next_check": nxt,
        "swing": swing,
    }


def build_review_ui(payload: dict[str, Any]) -> dict[str, Any]:
    ticker = str(payload.get("ticker") or "")
    name = str(payload.get("legal_name") or ticker or "该公司")
    hero = payload.get("hero") or {}
    cases = payload.get("cases") or {}
    implied = payload.get("market_implied") or {}
    customer = payload.get("customer_side") or {}
    delivery = payload.get("delivery_history") or {}
    chain = payload.get("causal_chain") or {}
    valuation = payload.get("valuation") or {}
    tree = payload.get("assumption_tree") or {}
    golden = {
        "top_assumptions": hero.get("top_assumptions") or [],
        "fragile_assumption": hero.get("weakest_assumption") or {},
        "strongest_assumption": hero.get("strongest_assumption") or {},
    }
    industry = bool(customer.get("industry_demand_confirmation") or hero.get("industry_demand"))
    named = bool(customer.get("named_issuer_cross_check_present"))
    direct = int(customer.get("direct_issuer_cross_check") or 0) > 0
    weakest = zh_layer(hero.get("weakest_layer") or chain.get("weakest_link"), ticker)
    vs_base = str(implied.get("vs_pm_base") or "")
    if vs_base == "below":
        gap_line = "当前股价隐含的增长预期明显低于基准情形"
        judgment_note = "当前市场预期明显低于基准情形，主要分歧在增长持续性与客户部署。"
    elif vs_base == "above":
        gap_line = "当前股价隐含的增长预期高于基准情形"
        judgment_note = "当前市场预期高于基准情形，需要确认增长是否被过早计入价格。"
    else:
        gap_line = "当前股价与基准情形的增长预期尚未形成清晰分歧"
        judgment_note = "市场与基准情形的增长预期尚未拉开，仍需用兑现和客户验证来校准。"
    if named:
        demand_line = "独立客户公开文件已交叉验证公司合同"
    elif industry:
        demand_line = "行业需求已有独立证据，但该公司具体合同仍未获客户侧确认"
    else:
        demand_line = "客户侧独立验证仍然不足"
    headline = (
        f"{name} 的中长期增长目前主要由已披露合同和管理层指引支撑，{demand_line}。"
        f"{gap_line}，核心风险是{weakest}兑现和增长持续性。"
    )
    if not hero.get("core_thesis") or hero.get("core_thesis") == "Missing":
        headline = f"{name} 的投资逻辑仍不完整。{demand_line}。估值与关键假设需要继续补证据。"
    why_watch = "中长期增长取决于已披露承诺能否兑现，因此仍值得跟踪。"
    strongest = hero.get("strongest_assumption") or {}
    if strongest.get("status") == "strengthened":
        why_watch = "证据最强的关键假设是管理层对多年合同的兑现能力，这是当前值得关注的主因。"
    elif strongest.get("statement"):
        why_watch = "已有被研究过的核心假设，但强度仍不足以单独定案。"
    biggest_risk = zh_gap(hero.get("biggest_unresolved_gap"))
    if weakest:
        biggest_risk = f"{weakest}仍是最容易断裂的一环；{biggest_risk}"
    monitors = [_monitor_zh(row, weakest) for row in (payload.get("monitoring") or [])[:5]]
    next_check = (monitors[0]["item"] if monitors else "下一次官方更新")
    ledger = list(payload.get("commitment_ledger") or [])
    buckets = {"delivered": 0, "pending": 0, "delayed": 0, "broken": 0}
    for row in ledger:
        buckets[_ledger_bucket(row.get("delivery_status") or row.get("status"))] += 1
    next_commit = next((row.get("next_check") for row in ledger if row.get("next_check")), "下次财报对照承诺")
    scored = int(delivery.get("prints_scored") or 0)
    beat = int(delivery.get("beat") or 0)
    missed = int(delivery.get("missed") or 0)
    met = int(delivery.get("met") or 0)
    delivery_note = "有效样本仍少于完整 6–8 季历史，不能视为长期可信度证明。" if scored < 6 else "兑现记录是历史对照，不是未来保证。"
    reliability = zh_status(hero.get("valuation_status") or valuation.get("status"))
    why_prov = "；".join(zh_missing(item) for item in (hero.get("why_provisional") or valuation.get("why_provisional") or []))
    layers = []
    for row in chain.get("layers") or []:
        label = zh_layer(row.get("layer"), ticker)
        if row.get("label") and str(row.get("layer")) not in LAYER_ZH:
            label = str(row.get("label"))
        layers.append(
            {
                "layer": row.get("layer"),
                "label": label,
                "strength": _strength(row.get("confidence"), bool(row.get("weakest")), bool(row.get("bottleneck"))),
                "weakest": bool(row.get("weakest")),
                "unresolved": [zh_gap(item) for item in (row.get("unresolved") or [])],
                "evidence": row.get("evidence") or [],
                "family": zh_family(row.get("evidence_family")),
            }
        )
    case_ui = {}
    for key, label in (("bear", "悲观"), ("market_implied", "市场隐含"), ("base", "基准"), ("bull", "乐观")):
        row = cases.get(key) or {}
        growth = _growth(row, implied_range=implied.get("market_implied_range_display") if key == "market_implied" else None)
        case_ui[key] = {
            "label": label,
            "target": _money_target(row.get("target")),
            "eps": row.get("eps") if row.get("eps") not in (None, "") else "待补",
            "growth": growth,
            "multiple": row.get("multiple") if row.get("multiple") not in (None, "") else "待补",
        }
    customer_summary = "行业需求真实，但该公司具体合同仍只有公司侧证据。" if industry and not named else (
        "独立客户已能交叉验证公司合同。" if named else "客户侧独立验证尚未建立。"
    )
    for branch in tree.get("branches") or []:
        branch["title_zh"] = BRANCH_ZH.get(str(branch.get("title") or ""), branch.get("title"))
        for node in branch.get("nodes") or []:
            node["status_label"] = zh_status(node.get("status"))
            node["role_label"] = zh_status(node.get("thesis_role"))
            node["unresolved_zh"] = [zh_gap(item) for item in (node.get("unresolved") or [])]
    return {
        "page_title": "投资研究",
        "headline": headline,
        "confidence_band": _band(hero.get("confidence")),
        "confidence_value": hero.get("confidence"),
        "valuation_reliability": reliability,
        "valuation_why": why_prov,
        "spot": hero.get("spot"),
        "why_watch": why_watch,
        "biggest_risk": biggest_risk,
        "next_check": next_check,
        "judgment_note": judgment_note,
        "cases": case_ui,
        "key_assumptions": _key_assumptions(tree, golden),
        "chain": layers,
        "weakest_layer": weakest,
        "monitor": monitors,
        "customer": {
            "industry": industry,
            "named": named,
            "direct": direct,
            "summary": customer_summary,
        },
        "ledger_summary": {
            "total": len(ledger),
            **buckets,
            "next": zh_gap(next_commit) if next_commit else "下次财报对照承诺",
        },
        "delivery_summary": {
            "scored": scored,
            "beat": beat,
            "met": met,
            "missed": missed,
            "note": delivery_note,
        },
        "missing": [zh_missing(item) for item in (payload.get("missing") or [])],
    }
