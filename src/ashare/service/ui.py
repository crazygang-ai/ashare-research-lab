"""Lightweight HTML page for local artifact review."""

from __future__ import annotations

from html import escape

from ashare.service.artifacts import ArtifactRegistry
from ashare.service.config import ServiceConfig
from ashare.service.queries import database_available


def render_index_html(config: ServiceConfig, registry: ArtifactRegistry) -> str:
    artifacts = registry.list_artifacts(limit=50)
    db_status = "available" if database_available(config) else "missing"
    cards = "\n".join(_artifact_card(artifact.to_dict()) for artifact in artifacts)
    if not cards:
        cards = "<p class=\"muted\">No generated artifacts found.</p>"
    latest_links = "\n".join(
        _latest_link(registry, kind)
        for kind in ["scan", "scoring", "backtest", "factor_validation"]
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Ashare Research Review</title>
  <style>
    :root {{
      color-scheme: light;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f6f7f8;
      color: #1f2933;
    }}
    body {{ margin: 0; }}
    main {{ max-width: 1080px; margin: 0 auto; padding: 28px 20px 48px; }}
    h1 {{ font-size: 28px; margin: 0 0 6px; }}
    h2 {{ font-size: 18px; margin: 28px 0 12px; }}
    .notice {{ color: #394b59; margin: 0 0 22px; }}
    .status, .artifact, form {{
      background: #ffffff;
      border: 1px solid #d8dee4;
      border-radius: 8px;
      padding: 14px 16px;
      margin-bottom: 12px;
    }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 10px; }}
    .artifact h3 {{ margin: 0 0 8px; font-size: 15px; }}
    .muted, .meta {{ color: #667085; font-size: 13px; }}
    code {{ font-size: 12px; overflow-wrap: anywhere; }}
    a {{ color: #005ea8; }}
    label {{ display: block; font-size: 13px; color: #394b59; margin: 8px 0 4px; }}
    input {{ width: 100%; box-sizing: border-box; padding: 8px; border: 1px solid #c7d0d9; border-radius: 6px; }}
  </style>
</head>
<body>
<main>
  <h1>A-share 研究复盘</h1>
  <p class="notice">服务仅用于研究查询，不是交易指令。This is not a trading system.</p>
  <section class="status">
    <strong>Service status</strong>
    <div class="meta">DuckDB query database: {escape(db_status)}</div>
    <div class="meta">DB path: <code>{escape(config.repo_relative(config.database_path))}</code></div>
  </section>
  <h2>Latest Entries</h2>
  <div class="grid">{latest_links}</div>
  <h2>Stock Factor Query</h2>
  <form method="get" action="/api/v1/stocks/000001.SZ/factors">
    <label>Endpoint</label>
    <input value="/api/v1/stocks/{{stock_code}}/factors?as_of=2026-06-26&amp;source_run_id=phase4-service" readonly>
  </form>
  <h2>Artifacts</h2>
  <div>{cards}</div>
</main>
</body>
</html>
"""


def _latest_link(registry: ArtifactRegistry, kind: str) -> str:
    artifact = registry.latest(kind)
    if artifact is None:
        return f"<div class=\"artifact\"><h3>{escape(kind)}</h3><p class=\"muted\">No artifact.</p></div>"
    label = escape(artifact.title)
    return (
        "<div class=\"artifact\">"
        f"<h3>{escape(kind)}</h3>"
        f"<a href=\"/api/v1/{_kind_endpoint(kind)}/latest\">{label}</a>"
        f"<div class=\"meta\">{escape(artifact.updated_at)}</div>"
        "</div>"
    )


def _artifact_card(artifact: dict[str, object]) -> str:
    artifact_id = escape(str(artifact["artifact_id"]))
    kind = escape(str(artifact["kind"]))
    title = escape(str(artifact["title"]))
    output_dir = escape(str(artifact["output_dir"]))
    updated_at = escape(str(artifact["updated_at"]))
    markdown_link = f"/api/v1/reports/{artifact_id}/markdown"
    return (
        "<article class=\"artifact\">"
        f"<h3>{title}</h3>"
        f"<div class=\"meta\">kind: {kind} · updated: {updated_at}</div>"
        f"<div class=\"meta\"><code>{output_dir}</code></div>"
        f"<a href=\"{markdown_link}\">raw markdown</a>"
        "</article>"
    )


def _kind_endpoint(kind: str) -> str:
    return {
        "scan": "scans",
        "scoring": "scoring",
        "backtest": "backtests",
        "factor_validation": "factors/return_20d/validation",
    }[kind]
