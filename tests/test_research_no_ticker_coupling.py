from pathlib import Path

import re


ROOT = Path(__file__).resolve().parents[1] / "src" / "stock_pm" / "research"
TICKER_BRANCH = re.compile(
    r"""if\s*\(\s*(ticker|symbol)\s*(==|!=)\s*['\"](AVGO|NVDA|XOM|COHR|AAPL)['\"]""",
    re.I,
)
COMMITMENT = re.compile(r"30\s*GW|thirty\s*gigawatt", re.I)


def test_research_package_has_no_ticker_specific_branches() -> None:
    offenders = []
    for path in ROOT.rglob("*"):
        if path.suffix not in {".py", ".json", ".md"}:
            continue
        if path.name == "issuer_directory.json":
            continue
        text = path.read_text(encoding="utf-8")
        if TICKER_BRANCH.search(text) or COMMITMENT.search(text):
            offenders.append(str(path.relative_to(ROOT.parent.parent.parent)))
    assert offenders == []
