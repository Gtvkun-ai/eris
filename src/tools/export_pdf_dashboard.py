# -*- coding: utf-8 -*-
"""Render a dependency-free HTML dashboard from pdf_acceptance.v3 JSON.

PDF annotation, pages 18-19: rollout needs a dashboard that shows latency,
quota pressure, 429s, shedding and semantic evaluation together.  The output is
static HTML so it can be opened on the ERIS machine without another service.
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any, Mapping


def _fmt(value: Any) -> str:
    if value is None:
        return "chưa có dữ liệu"
    if isinstance(value, bool):
        return "PASS" if value else "FAIL"
    if isinstance(value, float):
        return f"{value:,.3f}"
    return html.escape(str(value))


def render(report: Mapping[str, Any]) -> str:
    latency = dict(report.get("latency_ms", {}) or {})
    ttft = dict(report.get("ttft_ms", {}) or {})
    calls = dict(report.get("remote_calls_per_user_turn", {}) or {})
    rate = dict(report.get("rate_limits", {}) or {})
    tokens = dict(report.get("tokens", {}) or {})
    cancellation = dict(report.get("cancellation", {}) or {})
    observer = dict(report.get("observer", {}) or {})
    semantic = dict(report.get("semantic", {}) or {})
    acceptance = dict(report.get("acceptance", {}) or {})

    cards = [
        ("P50 small talk", f"{_fmt(latency.get('p50'))} ms"),
        ("P95 small talk", f"{_fmt(latency.get('p95'))} ms"),
        ("P95 TTFT", f"{_fmt(ttft.get('p95'))} ms"),
        ("Calls / turn", _fmt(calls.get("average"))),
        ("Optional 429", _fmt(rate.get("optional_lane_429"))),
        ("Chat 429", _fmt(rate.get("chat_lane_429"))),
        ("Background / chat tokens", _fmt(tokens.get("background_to_chat_ratio"))),
        ("Coalesced jobs", _fmt(cancellation.get("coalesced_jobs"))),
        ("Cancel before start", _fmt(cancellation.get("cancel_before_start"))),
        ("Observer in-flight discard", _fmt(observer.get("inflight_discard_rate"))),
        ("Semantic accuracy", _fmt(semantic.get("paraphrase_accuracy"))),
    ]
    card_html = "".join(
        f'<article class="card"><h3>{html.escape(title)}</h3><strong>{value}</strong></article>'
        for title, value in cards
    )
    rows = "".join(
        f"<tr><td>{html.escape(key)}</td><td class={'pass' if value is True else 'fail' if value is False else 'unknown'}>{_fmt(value)}</td></tr>"
        for key, value in sorted(acceptance.items())
    )
    raw = html.escape(json.dumps(report, ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ERIS PDF Refactor Dashboard</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0;background:#11151a;color:#edf2f7}}main{{max-width:1200px;margin:auto;padding:28px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}}.card{{background:#1b232c;border:1px solid #34404c;border-radius:12px;padding:16px}}
h1,h2,h3{{margin-top:0}}strong{{font-size:1.45rem}}table{{width:100%;border-collapse:collapse;background:#1b232c}}td{{padding:10px;border-bottom:1px solid #34404c}}
.pass{{color:#86efac}}.fail{{color:#fca5a5}}.unknown{{color:#fde68a}}details{{margin-top:20px}}pre{{white-space:pre-wrap;background:#0b0f13;padding:16px;border-radius:10px;overflow:auto}}
</style></head><body><main>
<h1>ERIS PDF Refactor Dashboard</h1><p>Schema: {html.escape(str(report.get('schema','unknown')))}</p>
<section class="grid">{card_html}</section>
<h2>Acceptance criteria</h2><table>{rows}</table>
<details><summary>Dữ liệu JSON đầy đủ</summary><pre>{raw}</pre></details>
</main></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Xuất dashboard HTML từ báo cáo acceptance PDF")
    parser.add_argument("--report", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    source = Path(args.report)
    if not source.exists():
        raise SystemExit(f"Không tìm thấy report: {source}")
    payload = json.loads(source.read_text(encoding="utf-8"))
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(payload), encoding="utf-8")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
