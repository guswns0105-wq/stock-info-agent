#!/usr/bin/env python3
"""Ensure both stock cardnews assets exist before dashboard rendering.

This is the local-pack informed repair harness for the stock dashboard: ImageGen2
may fail or a publisher run may delete one market image, but the public dashboard
should not silently drop the overseas/KR visual panel.  This script reads
`data/imagegen2/cardnews_prompts.json` and `data/valuations.json`, then creates a
clean deterministic PNG fallback for every missing/undersized spec asset.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIN_BYTES = 100_000
PROMPTS = ROOT / "data" / "imagegen2" / "cardnews_prompts.json"
VALUATIONS = ROOT / "data" / "valuations.json"


def load_specs() -> list[dict]:
    raw = json.loads(PROMPTS.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("specs", [])
    if not isinstance(raw, list):
        raise SystemExit("cardnews_prompts.json must be a list or {'specs': [...]} object")
    return [x for x in raw if isinstance(x, dict) and x.get("asset_path")]


def load_recommendations() -> dict[str, list[dict]]:
    data = json.loads(VALUATIONS.read_text(encoding="utf-8"))
    recs = data.get("ai_recommendations", {})
    if isinstance(recs, list):
        grouped = {"domestic": [], "global": []}
        for row in recs:
            grouped.setdefault(row.get("region", "domestic"), []).append(row)
        return grouped
    return {"domestic": recs.get("domestic", []), "global": recs.get("global", [])}


def font(size: int):
    from PIL import ImageFont

    candidates = [
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def money(value, currency: str) -> str:
    try:
        v = float(value)
    except Exception:
        return "확인 불가"
    if currency == "KRW":
        return f"{v:,.0f}원"
    if currency:
        return f"${v:,.2f}" if currency == "USD" else f"{v:,.2f} {currency}"
    return f"{v:,.2f}"


def draw_fallback(spec: dict, rows: list[dict], out: Path) -> None:
    from PIL import Image, ImageDraw

    region = spec.get("region") or "global"
    label = spec.get("label") or ("한국주식" if region == "domestic" else "미국주식")
    accent = (18, 150, 105) if region == "domestic" else (42, 105, 210)
    accent2 = (62, 180, 135) if region == "domestic" else (38, 170, 150)
    W, H = 1080, 1920
    img = Image.new("RGB", (W, H), (247, 250, 255))
    d = ImageDraw.Draw(img)

    f_title, f_sub, f_rank = font(78), font(34), font(38)
    f_name, f_body, f_small, f_foot = font(46), font(30), font(24), font(26)

    d.ellipse((650, -120, 1180, 420), fill=(226, 238, 255))
    d.ellipse((760, 80, 1260, 570), fill=(228, 248, 242))
    d.text((70, 70), f"{label} Top 5", font=f_title, fill=(15, 28, 55))
    d.text((74, 160), "관심종목 · 적정가격 참고 · 투자 추천 아님", font=f_sub, fill=(72, 92, 130))

    y = 245
    palette = [accent, accent2, (85, 95, 190), accent2, accent]
    for idx, row in enumerate(rows[:5], 1):
        x, card_h = 70, 275
        d.rounded_rectangle((x, y, W - 70, y + card_h), radius=34, fill=(255, 255, 255), outline=(214, 225, 242), width=3)
        d.rounded_rectangle((x, y, x + 12, y + card_h), radius=6, fill=palette[idx - 1])
        d.ellipse((x + 36, y + 34, x + 96, y + 94), fill=palette[idx - 1])
        d.text((x + 66, y + 64), str(idx), font=f_rank, fill=(255, 255, 255), anchor="mm")
        name = f"{row.get('name', '')}  {row.get('ticker', '')}".strip()
        d.text((x + 125, y + 32), name[:30], font=f_name, fill=(15, 28, 55))
        verdict = row.get("verdict") or "관심권"
        badge_fill = (235, 246, 241) if "저평가" in verdict else (239, 243, 255)
        d.rounded_rectangle((W - 260, y + 38, W - 105, y + 82), radius=20, fill=badge_fill)
        d.text((W - 248, y + 45), verdict[:8], font=f_small, fill=(28, 118, 84) if "저평가" in verdict else (57, 78, 160))

        cur = money(row.get("price"), row.get("currency", ""))
        fair = money(row.get("fair_value"), row.get("currency", ""))
        d.text((x + 125, y + 105), f"현재가 {cur}", font=f_body, fill=(55, 68, 92))
        d.text((x + 125, y + 150), f"AI가 보는 적정가격 {fair}", font=f_body, fill=(20, 105, 80))
        comment = " ".join(str(row.get("comment") or "공개 출처·재무·차트 기준으로 산정했습니다.").split())[:54]
        d.text((x + 125, y + 198), comment, font=f_small, fill=(85, 98, 125))

        base_y = y + 228
        pts = [(W - 315, base_y), (W - 255, base_y - 24), (W - 205, base_y - 10), (W - 155, base_y - 42), (W - 105, base_y - 30)]
        d.line(pts, fill=palette[idx - 1], width=6)
        for px, py in pts:
            d.ellipse((px - 5, py - 5, px + 5, py + 5), fill=palette[idx - 1])
        y += card_h + 32

    d.rounded_rectangle((70, H - 130, W - 70, H - 55), radius=24, fill=(235, 241, 250))
    d.text((W / 2, H - 92), "공개 출처·재무지표·차트 위치를 함께 본 참고용 요약입니다", font=f_foot, fill=(65, 80, 110), anchor="mm")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, quality=95)


def main() -> None:
    specs = load_specs()
    recs = load_recommendations()
    repaired = []
    ok = []
    for spec in specs:
        asset = ROOT / spec["asset_path"] if not str(spec["asset_path"]).startswith(str(ROOT)) else Path(spec["asset_path"])
        good = asset.exists() and asset.stat().st_size >= MIN_BYTES
        if not good:
            rows = spec.get("recommendations") or recs.get(spec.get("region", ""), [])
            if not rows:
                raise SystemExit(f"No recommendation rows available to repair {asset}")
            draw_fallback(spec, rows, asset)
            repaired.append(str(asset.relative_to(ROOT)))
        if not asset.exists() or asset.stat().st_size < MIN_BYTES:
            raise SystemExit(f"Cardnews asset missing/undersized after repair: {asset}")
        ok.append((str(asset.relative_to(ROOT)), asset.stat().st_size))
    print(json.dumps({"ok": ok, "repaired": repaired, "min_bytes": MIN_BYTES}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
