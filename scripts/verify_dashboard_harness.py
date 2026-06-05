#!/usr/bin/env python3
"""Hard verification harness for the public stock dashboard.

Fails fast when the page would silently ship without one of the required market
sections or with a stale/broken cardnews image reference. This encodes the
source/evidence gates for the user's stock dashboard and is intentionally
stricter than the renderer. If ImageGen2 fails, missing assets are allowed only
when the generated HTML omits them.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIN_IMAGE_BYTES = 100_000


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def fail(msg: str) -> None:
    raise AssertionError(msg)


def html_slice(html: str, start: str, end: str) -> str:
    a = html.find(start)
    b = html.find(end)
    if a < 0 or b < 0 or a >= b:
        fail(f"HTML order/slice invalid: {start} -> {end}")
    return html[a:b]


def specs_list(raw):
    if isinstance(raw, dict):
        raw = raw.get("specs", [])
    if not isinstance(raw, list):
        fail("cardnews_prompts.json must be a list or {'specs': [...]} object")
    return raw


def verify() -> dict:
    html_path = ROOT / "public" / "index.html"
    html = html_path.read_text(encoding="utf-8")
    vals = load_json(ROOT / "data" / "valuations.json")
    specs = specs_list(load_json(ROOT / "data" / "imagegen2" / "cardnews_prompts.json"))
    sources = load_json(ROOT / "config" / "sources.json")
    common = load_json(ROOT / "data" / "common_recommendations.json")
    items = load_json(ROOT / "data" / "items.json")

    recs = vals.get("ai_recommendations", {})
    if isinstance(recs, list):
        grouped = {"domestic": [], "global": []}
        for row in recs:
            grouped.setdefault(row.get("region", "domestic"), []).append(row)
        recs = grouped
    domestic = recs.get("domestic", [])
    global_rows = recs.get("global", [])
    if len(domestic) != 5:
        fail(f"domestic Top5 count != 5: {[r.get('ticker') for r in domestic]}")
    if len(global_rows) != 5:
        fail(f"global Top5 count != 5: {[r.get('ticker') for r in global_rows]}")
    over_fair = [
        (market, r.get("ticker"), r.get("price"), r.get("fair_value"))
        for market, rows in (("domestic", domestic), ("global", global_rows))
        for r in rows
        if float(r.get("fair_value") or 0) < float(r.get("price") or 0)
    ]
    if over_fair:
        fail(f"Top5 contains over-fair rows: {over_fair}")

    required_strings = [
        "id=\"top-recommendations\"",
        "국내주식 AI 관심종목 Top5",
        "미국주식 AI 관심종목 Top5",
        "id=\"global\"",
        "화면근거:",
        "overflow-x: hidden",
    ]
    for needle in required_strings:
        if needle not in html:
            fail(f"Required HTML string missing: {needle}")
    if "로컬팩" in html or "local pack" in html.lower():
        fail("Internal local-pack wording leaked into public HTML")
    top = html_slice(html, 'id="top-recommendations"', 'id="news"')
    if "미국주식 AI 관심종목 Top5" not in top:
        fail("Global/US Top5 is not inside the top recommendation slice")

    expected_regions = {"domestic", "global"}
    spec_regions = {s.get("region") for s in specs if isinstance(s, dict)}
    if not expected_regions.issubset(spec_regions):
        fail(f"Cardnews specs missing regions: {expected_regions - spec_regions}")
    asset_report = []
    for spec in specs:
        asset_path = spec.get("asset_path")
        region = spec.get("region")
        if region not in expected_regions or not asset_path:
            continue
        asset = ROOT / asset_path
        rel = asset_path.replace("public/", "", 1)
        exists = asset.exists()
        size = asset.stat().st_size if exists else 0
        included = rel in html
        if not exists or size < MIN_IMAGE_BYTES:
            if included:
                fail(f"{region} cardnews asset is missing/undersized but still referenced in HTML: {rel} size={size}")
            asset_report.append({"region": region, "path": rel, "size": size, "status": "omitted_after_imagegen2_failure"})
            continue
        if not included:
            fail(f"Available {region} cardnews asset not referenced in HTML: {rel}")
        asset_report.append({"region": region, "path": rel, "size": size, "status": "included"})

    youtube_channels = [
        x
        for bucket in ("domestic", "global")
        for x in sources.get(bucket, [])
        if x.get("type") == "youtube_channel"
    ]
    if not youtube_channels:
        fail("No YouTube channels configured")
    missing_skip = [x.get("name") for x in youtube_channels if x.get("skip_existing_video_ids") is not True]
    if missing_skip:
        fail(f"YouTube sources missing duplicate-skip: {missing_skip}")

    macro_ticker_items = [
        i.get("url")
        for i in items
        if (("ranto28" in str(i.get("url", "")).lower()) or i.get("source") == "메르의 블로그") and i.get("tickers")
    ]
    if macro_ticker_items:
        fail(f"메르/ranto28 ticker leakage: {macro_ticker_items[:3]}")
    ranto_evidence = [
        ev.get("url")
        for row in common
        for ev in row.get("evidence", [])
        if "ranto28" in str(ev.get("url", "")).lower() or "ranto28" in str(ev.get("source", "")).lower()
    ]
    if ranto_evidence:
        fail(f"메르/ranto28 common evidence leakage: {ranto_evidence[:3]}")

    return {
        "status": "PASS",
        "items": len(items),
        "domestic": [r.get("ticker") for r in domestic],
        "global": [r.get("ticker") for r in global_rows],
        "assets": asset_report,
        "youtube_channels": len(youtube_channels),
    }


if __name__ == "__main__":
    try:
        print(json.dumps(verify(), ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"DASHBOARD_HARNESS_FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
