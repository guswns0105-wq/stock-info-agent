#!/usr/bin/env python3
"""Prepare ImageGen2 prompts for stock Top5 card-news assets.

This script does not call an image API. It reads data/valuations.json after the
hourly valuation pass and writes deterministic prompt/spec files that a Hermes
cron agent can feed into image_generate, then copy the generated PNGs into
public/assets/imagegen2/.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALUATIONS = ROOT / "data" / "valuations.json"
OUT_DIR = ROOT / "data" / "imagegen2"
PROMPTS = OUT_DIR / "cardnews_prompts.json"
SOURCE_MD = OUT_DIR / "cardnews_source.md"


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def money(value, currency):
    if value is None:
        return "확인 중"
    try:
        value = float(value)
    except Exception:
        return str(value)
    if currency == "USD":
        return f"${value:,.2f}"
    return f"{value:,.0f}원"


def region_label(region: str) -> str:
    return "한국주식" if region == "domestic" else "미국주식"


def top_recs(data, region):
    recs = data.get("ai_recommendations", []) if isinstance(data, dict) else []
    if isinstance(recs, dict):
        arr = recs.get(region, [])
    else:
        arr = [r for r in recs if r.get("region") == region]
    arr = sorted(arr, key=lambda r: (r.get("rank") or 99, -(r.get("ai_score") or 0)))[:5]
    # Fallback from valuations if grouped recommendation data is missing.
    if len(arr) < 5:
        vals = data.get("valuations", []) if isinstance(data, dict) else []
        seen = {r.get("ticker") for r in arr}
        extra = []
        for v in vals:
            if v.get("region") != region or v.get("ticker") in seen:
                continue
            extra.append(v)
        extra = sorted(extra, key=lambda v: (v.get("score") or 0), reverse=True)
        for v in extra:
            if len(arr) >= 5:
                break
            arr.append({
                "rank": len(arr) + 1,
                "ticker": v.get("ticker"),
                "name": v.get("name"),
                "price": v.get("price"),
                "fair_value": v.get("fair_value"),
                "currency": v.get("currency"),
                "comment": v.get("ai_comment") or v.get("rationale") or "관심 후보로 다시 확인",
                "risk_comment": "; ".join((v.get("risks") or [])[:1]) or "변동성 확인",
            })
    # Ensure rank is 1..N and text is short for image models.
    for i, r in enumerate(arr[:5], 1):
        r["rank"] = i
    return arr[:5]


def compact_comment(text: str) -> str:
    text = " ".join(str(text or "관심 후보로 다시 확인").replace("\n", " ").split())
    replacements = {
        "전기차와 완성차 회복 기대가 같이 보이는 종목": "전기차·완성차 회복 기대",
        "실적 체력과 밸류에이션 매력이 함께 보이는 자동차 대표주": "실적 체력과 저평가 매력",
        "AI 메모리 수요와 HBM 기대가 이어지는 반도체 대표주": "AI 메모리·HBM 기대",
        "광고 회복과 AI 투자 효율을 같이 보는 빅테크": "광고 회복 + AI 효율",
        "클라우드와 AI 소프트웨어 수익성이 안정적인 대표주": "클라우드 + AI 소프트웨어",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    if len(text) > 26:
        text = text[:25].rstrip() + "…"
    return text


def compact_risk(text: str) -> str:
    text = " ".join(str(text or "변동성 확인").replace("\n", " ").split())
    text = text.replace("주의:", "").replace("리스크:", "").strip()
    if len(text) > 16:
        text = text[:15].rstrip() + "…"
    return text or "변동성 확인"


def prompt_for(region: str, recs: list[dict]) -> str:
    title = f"{region_label(region)} Top 5"
    accent = "green/red" if region == "domestic" else "blue/green"
    lines = [
        "Korean financial card news poster, portrait 9:16, clean premium white finance dashboard style.",
        "IMPORTANT: render readable Korean text exactly; no gibberish; no misspellings; all text horizontal and inside cards.",
        f"Style: five vertical rounded cards, thin black typography, subtle {accent} market accents, small abstract chart lines, no company logos, no watermark.",
        "",
        f"Title: {title}",
        "Subtitle: 적정가격과 한 줄 설명",
        "",
    ]
    for r in recs:
        rank = r.get("rank")
        name = r.get("name") or r.get("ticker") or "종목"
        ticker = r.get("ticker") or ""
        currency = r.get("currency") or ("USD" if region == "global" else "KRW")
        lines += [
            f"{rank} {name} {ticker}",
            f"현재가 {money(r.get('price'), currency)} / 적정 {money(r.get('fair_value'), currency)}",
            compact_comment(str(r.get("comment") or r.get("ai_comment") or r.get("rationale") or "관심 후보로 다시 확인")),
            f"주의: {compact_risk(str(r.get('risk_comment') or '; '.join((r.get('risks') or [])[:1]) or '변동성 확인'))}",
            "",
        ]
    lines += [
        "Footer: 정보 요약용 · 투자 추천 아님",
        "Use generous safe margins, large Korean typography, high contrast, clear card separation.",
        "Avoid: tiny text, blurred text, broken Korean, random English, logo, watermark, overdecorated background.",
    ]
    return "\n".join(lines)


def main():
    data = load_json(VALUATIONS, {})
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    specs = []
    md_lines = [f"# ImageGen2 stock cardnews source", "", f"Generated: {datetime.now().isoformat(timespec='minutes')}", ""]
    for region, filename in [("domestic", "korea-top5-cardnews.png"), ("global", "us-top5-cardnews.png")]:
        recs = top_recs(data, region)
        specs.append({
            "region": region,
            "label": region_label(region),
            "asset_path": f"public/assets/imagegen2/{filename}",
            "prompt": prompt_for(region, recs),
            "recommendations": recs,
        })
        md_lines.append(f"## {region_label(region)}")
        for r in recs:
            currency = r.get("currency") or ("USD" if region == "global" else "KRW")
            md_lines.append(f"{r.get('rank')}. {r.get('name')} {r.get('ticker')} — 현재가 {money(r.get('price'), currency)}, 적정 {money(r.get('fair_value'), currency)}")
        md_lines.append("")
    PROMPTS.write_text(json.dumps(specs, ensure_ascii=False, indent=2), encoding="utf-8")
    SOURCE_MD.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"Wrote {PROMPTS} specs={len(specs)}")
    for spec in specs:
        tickers = ",".join(r.get("ticker", "") for r in spec["recommendations"])
        print(f"{spec['region']}: {tickers}")


if __name__ == "__main__":
    main()
