from __future__ import annotations

from pathlib import Path

import yaml


def test_ashare_skill_frontmatter_and_required_content() -> None:
    skill = Path("skills/ashare-research-lab/SKILL.md")
    text = skill.read_text(encoding="utf-8")

    assert text.startswith("---")
    frontmatter = text.split("---", 2)[1]
    meta = yaml.safe_load(frontmatter)
    assert meta["name"] == "ashare-research-lab"
    assert "ashare-research-lab" in meta["description"]
    required = [
        "conda run -n ashare-research-lab",
        "fixture",
        "factor validation",
        "candidate",
        "scoring",
        "backtest",
        "serve",
        "not a trading instruction",
        "Do not commit generated artifacts",
    ]
    missing = [item for item in required if item not in text]
    assert not missing
    forbidden = ["sk-", "buy signal", "sell signal"]
    assert not any(item in text for item in forbidden)
