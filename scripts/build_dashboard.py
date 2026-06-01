#!/usr/bin/env python3
import html
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'items.json'
COMMON = ROOT / 'data' / 'common_recommendations.json'
PACKCTX = ROOT / 'data' / 'local_pack_context.json'
OUT = ROOT / 'public' / 'index.html'
LABEL = {'domestic': '국내', 'global': '해외'}


def load(path, default):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def esc(value):
    return html.escape(str(value or ''))


def badge(value, cls=''):
    return '' if not value else f'<span class="badge {cls}">{esc(value)}</span>'


def evidence_links(evidence):
    links = []
    for ev in evidence[:4]:
        url = esc(ev.get('url', ''))
        source = esc(ev.get('source', 'source'))
        links.append(f'<a href="{url}" target="_blank" rel="noreferrer">{source}</a>')
    return ' · '.join(links) or '근거 링크 없음'


def rec_card(rec):
    score = '★' * min(5, max(1, int(rec.get('source_count', 1))))
    notes = ''.join(
        f'<li><b>{esc(note.get("pack_id"))}</b>: {esc(note.get("note", ""))}</li>'
        for note in rec.get('local_pack_notes', [])[:2]
    ) or '<li>관련 로컬팩 메모 없음</li>'
    return f'''
    <article class="card rec-card">
      <div class="rec-head">
        <div>
          <h3>{esc(rec.get('name'))} <span class="ticker-text">{esc(rec.get('ticker'))}</span></h3>
          <p class="stance">{esc(rec.get('stance'))}</p>
        </div>
        <div class="score">{score}<br><small>{rec.get('source_count', 0)}개 소스</small></div>
      </div>
      <div class="badges">{badge(LABEL.get(rec.get('region'), rec.get('region')), 'region')}{badge('공통 관심', 'rec')}{badge('로컬팩 교차검증', 'conf')}</div>
      <p><b>근거 출처:</b> {evidence_links(rec.get('evidence', []))}</p>
      <p class="risk"><b>주의:</b> {esc(rec.get('risk'))}</p>
      <details><summary>로컬팩 근거 메모</summary><ul>{notes}</ul></details>
    </article>'''


def item_card(item):
    tickers = ''.join(badge(ticker, 'ticker') for ticker in item.get('tickers', []))
    link = f'<a class="source-link" href="{esc(item.get("url"))}" target="_blank" rel="noreferrer">원문</a>' if item.get('url') else ''
    when = item.get('published_at') or item.get('collected_at') or ''
    return f'''
    <article class="card small">
      <div class="meta"><strong>{esc(item.get('source'))}</strong><span>{esc(when)}</span>{link}</div>
      <h4>{esc(item.get('title'))}</h4>
      <p>{esc(item.get('summary'))}</p>
      <div class="badges">{badge(item.get('recommendation'), 'rec')}{tickers}</div>
    </article>'''


def section(region, common, items):
    recs = [rec for rec in common if rec.get('region') == region]
    details = [item for item in items if item.get('region') == region]
    rec_html = '\n'.join(rec_card(rec) for rec in recs) or '<p class="empty">공통 관심 종목이 아직 없습니다.</p>'
    detail_html = '\n'.join(item_card(item) for item in details[:12]) or '<p class="empty">수집 항목이 없습니다.</p>'
    return f'<section id="{region}" class="tabpanel"><h2>{LABEL[region]} 공통 관심 종목</h2>{rec_html}<h2>{LABEL[region]} 최신 소스 로그</h2>{detail_html}</section>'


def main():
    items = load(DATA, [])
    common = load(COMMON, [])
    packs = load(PACKCTX, [])
    generated = datetime.now().strftime('%Y-%m-%d %H:%M')
    total_sources = len(set(item.get('source') for item in items))
    doc = f'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>공통 종목추천 대시보드</title>
<style>
:root{{--panel:#121a33;--panel2:#182442;--text:#eef3ff;--muted:#9fb0d0;--accent:#65d6ff;--green:#89f7a5;--yellow:#ffe08a}}
*{{box-sizing:border-box}} body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:linear-gradient(135deg,#081020,#111a35);color:var(--text)}}
header,main{{max-width:1120px;margin:auto}} header{{padding:34px 22px 18px}} h1{{margin:0 0 8px;font-size:clamp(28px,5vw,46px)}} .subtitle,.meta,.empty{{color:var(--muted)}}
.kpis{{display:flex;gap:10px;flex-wrap:wrap;margin-top:16px}} .kpi{{background:rgba(101,214,255,.10);border:1px solid rgba(101,214,255,.25);padding:10px 14px;border-radius:14px}}
.tabs{{display:flex;gap:10px;max-width:1120px;margin:0 auto 16px;padding:0 22px}} .tabs a{{text-decoration:none;color:var(--text);background:var(--panel);border:1px solid #26385f;padding:10px 18px;border-radius:999px}}
main{{padding:0 22px 60px}} .notice{{background:rgba(255,224,138,.1);border:1px solid rgba(255,224,138,.25);border-radius:14px;padding:14px;color:#fff0be}} h2{{color:var(--accent);margin-top:30px}}
.card{{background:rgba(18,26,51,.94);border:1px solid #26385f;border-radius:18px;padding:18px;margin:14px 0;box-shadow:0 12px 32px rgba(0,0,0,.25)}} .small h4{{font-size:18px;margin:8px 0}} .card p{{color:#d9e4ff;line-height:1.56}}
.rec-head{{display:flex;justify-content:space-between;gap:16px}} .rec-head h3{{font-size:24px;margin:0 0 6px}} .ticker-text{{color:var(--green);font-size:18px}} .score{{text-align:right;color:var(--yellow);white-space:nowrap}} .stance{{margin:0;color:#eaf1ff}} .risk{{color:#ffd0d0!important}}
.meta{{display:flex;flex-wrap:wrap;gap:10px;font-size:14px}} a{{color:var(--accent)}} .badges{{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}} .badge{{display:inline-flex;padding:5px 10px;border-radius:999px;background:var(--panel2);color:#dbe7ff;font-size:13px}}
.ticker{{color:var(--green);border:1px solid rgba(137,247,165,.35)}} .rec{{color:var(--yellow);border:1px solid rgba(255,224,138,.35)}} .conf{{color:var(--accent)}} .region{{color:#fff}} details{{color:#cbd9ff}} footer{{color:var(--muted);text-align:center;padding:22px}}
</style></head>
<body>
<header><h1>공통 종목추천 대시보드</h1><div class="subtitle">유튜버 · 블로그 · 뉴스 · 로컬팩 기반 / 생성: {generated}</div><div class="kpis"><div class="kpi">수집 소스 {total_sources}개</div><div class="kpi">소스 로그 {len(items)}개</div><div class="kpi">관심 종목 {len(common)}개</div><div class="kpi">로컬팩 {len(packs)}개 연결</div></div></header>
<nav class="tabs"><a href="#domestic">국내</a><a href="#global">해외</a></nav>
<main><div class="notice">여러 출처에서 반복 언급된 종목을 ‘공통 관심’으로 배치합니다. 매수/매도 지시가 아니며, 최신 공시·실적·수급 확인이 필요합니다.</div>{section('domestic', common, items)}{section('global', common, items)}</main>
<footer>Generated by Hermes Stock Info Agent</footer>
</body></html>'''
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(doc, encoding='utf-8')
    print(f'Wrote {OUT} items={len(items)} common={len(common)}')


if __name__ == '__main__':
    main()
