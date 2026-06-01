#!/usr/bin/env python3
import html
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'items.json'
COMMON = ROOT / 'data' / 'common_recommendations.json'
OUT = ROOT / 'public' / 'index.html'
LABEL = {'domestic': '국내', 'global': '해외'}


def load(path, default):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def esc(value):
    return html.escape(str(value or ''))


def badge(value, cls=''):
    return '' if not value else f'<span class="badge {cls}">{esc(value)}</span>'


def short_date(value):
    if not value:
        return '날짜 미확인'
    return esc(str(value)[:10])


def evidence_rows(evidence):
    rows = []
    for ev in evidence[:6]:
        role = esc(ev.get('source_role') or '소스')
        source = esc(ev.get('source') or '출처')
        date = short_date(ev.get('published_at'))
        title = esc(ev.get('title') or '')
        reason = esc(ev.get('reason') or '추천 근거 문장 추출 대기')
        url = esc(ev.get('url') or '')
        target = esc(ev.get('target_price') or '출처에서 명시 안 됨')
        buy = esc(ev.get('buy_zone') or '출처에서 명시 안 됨')
        conf = '자막 기반' if ev.get('confidence') == 'transcript' else '제목/설명 기반'
        link = f'<a href="{url}" target="_blank" rel="noreferrer">원문</a>' if url else ''
        rows.append(f'''
        <li class="evidence-row">
          <div class="ev-top"><b>{role} {source}</b><span>{date}</span>{link}{badge(conf, 'conf' if ev.get('confidence') == 'transcript' else 'meta-badge')}</div>
          <div class="ev-title">{title}</div>
          <div class="ev-reason"><b>추천/언급 이유:</b> {reason}</div>
          <div class="price-grid"><span><b>적정가·목표가:</b> {target}</span><span><b>매수·진입가:</b> {buy}</span></div>
        </li>''')
    return '\n'.join(rows) or '<li class="evidence-row">근거 출처가 아직 없습니다.</li>'


def rec_card(rec):
    strength = '강한 반복 언급' if rec.get('source_count', 0) >= 3 else ('복수 출처 언급' if rec.get('source_count', 0) >= 2 else '단일 출처 언급')
    return f'''
    <article class="card rec-card">
      <div class="rec-head">
        <div>
          <h3>{esc(rec.get('name'))} <span class="ticker-text">{esc(rec.get('ticker'))}</span></h3>
          <p class="stance">{esc(rec.get('stance'))} · {strength}</p>
        </div>
        <div class="score"><strong>{rec.get('source_count', 0)}</strong><br><small>출처</small></div>
      </div>
      <div class="badges">{badge(LABEL.get(rec.get('region'), rec.get('region')), 'region')}{badge('추천/관심 종목', 'rec')}{badge(strength, 'type')}</div>
      <div class="summary-grid">
        <div><b>적정가·목표가</b><p>{esc(rec.get('target_price_summary'))}</p></div>
        <div><b>매수·진입가</b><p>{esc(rec.get('buy_zone_summary'))}</p></div>
      </div>
      <ul class="evidence-list">{evidence_rows(rec.get('evidence', []))}</ul>
      <p class="risk"><b>확인 필요:</b> {esc(rec.get('caution'))}</p>
    </article>'''


def item_card(item):
    tickers = ''.join(badge(ticker, 'ticker') for ticker in item.get('tickers', []))
    link = f'<a class="source-link" href="{esc(item.get("url"))}" target="_blank" rel="noreferrer">원문</a>' if item.get('url') else ''
    when = item.get('published_at') or item.get('collected_at') or ''
    confidence = badge('자막 기반', 'conf') if item.get('confidence') == 'transcript' else badge('제목/설명 기반', 'meta-badge')
    role = badge(item.get('source_role') or item.get('source_type', ''), 'type')
    return f'''
    <article class="card small">
      <div class="meta"><strong>{esc(item.get('source'))}</strong><span>{esc(short_date(when))}</span>{link}</div>
      <h4>{esc(item.get('title'))}</h4>
      <p>{esc(item.get('summary'))}</p>
      <div class="mini-price"><span>적정가: {esc(item.get('target_price'))}</span><span>매수/진입: {esc(item.get('buy_zone'))}</span></div>
      <div class="badges">{badge(item.get('recommendation'), 'rec')}{confidence}{role}{tickers}</div>
    </article>'''


def section(region, common, items):
    recs = [rec for rec in common if rec.get('region') == region]
    details = [item for item in items if item.get('region') == region]
    rec_html = '\n'.join(rec_card(rec) for rec in recs) or '<p class="empty">추천/관심 종목이 아직 없습니다.</p>'
    detail_html = '\n'.join(item_card(item) for item in details[:14]) or '<p class="empty">수집 항목이 없습니다.</p>'
    return f'<section id="{region}" class="tabpanel"><h2>{LABEL[region]} 추천/관심 종목</h2>{rec_html}<h2>{LABEL[region]} 소스별 최신 발언</h2>{detail_html}</section>'


def main():
    items = load(DATA, [])
    common = load(COMMON, [])
    generated = datetime.now().strftime('%Y-%m-%d %H:%M')
    total_sources = len(set(item.get('source') for item in items))
    doc = f'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>종목추천 소스 대시보드</title>
<style>
:root{{--panel:#121a33;--panel2:#182442;--text:#eef3ff;--muted:#9fb0d0;--accent:#65d6ff;--green:#89f7a5;--yellow:#ffe08a;--red:#ffd0d0}}
*{{box-sizing:border-box}} body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:radial-gradient(circle at top left,#18305f,#081020 45%,#070b16);color:var(--text)}}
header,main{{max-width:1180px;margin:auto}} header{{padding:36px 22px 18px}} h1{{margin:0 0 8px;font-size:clamp(28px,5vw,46px)}} .subtitle,.meta,.empty{{color:var(--muted)}}
.kpis{{display:flex;gap:10px;flex-wrap:wrap;margin-top:16px}} .kpi{{background:rgba(101,214,255,.10);border:1px solid rgba(101,214,255,.25);padding:10px 14px;border-radius:14px}}
.tabs{{display:flex;gap:10px;max-width:1180px;margin:0 auto 16px;padding:0 22px}} .tabs a{{text-decoration:none;color:var(--text);background:var(--panel);border:1px solid #26385f;padding:10px 18px;border-radius:999px}}
main{{padding:0 22px 60px}} .notice{{background:rgba(255,224,138,.1);border:1px solid rgba(255,224,138,.25);border-radius:14px;padding:14px;color:#fff0be;line-height:1.55}} h2{{color:var(--accent);margin-top:30px}}
.card{{background:rgba(18,26,51,.94);border:1px solid #26385f;border-radius:18px;padding:18px;margin:14px 0;box-shadow:0 12px 32px rgba(0,0,0,.25)}} .small h4{{font-size:18px;margin:8px 0}} .card p{{color:#d9e4ff;line-height:1.56}}
.rec-head{{display:flex;justify-content:space-between;gap:16px}} .rec-head h3{{font-size:24px;margin:0 0 6px}} .ticker-text{{color:var(--green);font-size:18px}} .score{{text-align:right;color:var(--yellow);white-space:nowrap}} .score strong{{font-size:26px}} .stance{{margin:0;color:#eaf1ff}} .risk{{color:var(--red)!important}}
.summary-grid,.price-grid,.mini-price{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}} .summary-grid>div{{background:rgba(101,214,255,.07);border:1px solid rgba(101,214,255,.16);border-radius:14px;padding:12px}} .summary-grid p{{margin:6px 0 0}}
.evidence-list{{list-style:none;padding:0;margin:14px 0 0}} .evidence-row{{border-top:1px solid #26385f;padding:12px 0}} .ev-top{{display:flex;flex-wrap:wrap;gap:10px;align-items:center;color:#dbe7ff}} .ev-title{{margin-top:6px;color:#fff}} .ev-reason{{margin-top:8px;color:#d9e4ff;line-height:1.5}}
.meta{{display:flex;flex-wrap:wrap;gap:10px;font-size:14px}} a{{color:var(--accent)}} .badges{{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}} .badge{{display:inline-flex;padding:5px 10px;border-radius:999px;background:var(--panel2);color:#dbe7ff;font-size:13px}}
.ticker{{color:var(--green);border:1px solid rgba(137,247,165,.35)}} .rec{{color:var(--yellow);border:1px solid rgba(255,224,138,.35)}} .conf{{color:var(--accent)}} .meta-badge{{color:#cbd9ff}} .region{{color:#fff}} .type{{color:#c8b6ff}} footer{{color:var(--muted);text-align:center;padding:22px}}
@media (max-width:760px){{.summary-grid,.price-grid,.mini-price{{grid-template-columns:1fr}} .rec-head{{display:block}} .score{{text-align:left;margin-top:8px}}}}
</style></head>
<body>
<header><h1>종목추천 소스 대시보드</h1><div class="subtitle">유튜버·블로거·뉴스가 왜 추천/언급했는지, 날짜와 가격 발언을 함께 정리합니다. / 생성: {generated}</div><div class="kpis"><div class="kpi">수집 소스 {total_sources}개</div><div class="kpi">소스 로그 {len(items)}개</div><div class="kpi">추천/관심 종목 {len(common)}개</div></div></header>
<nav class="tabs"><a href="#domestic">국내</a><a href="#global">해외</a></nav>
<main><div class="notice">이 페이지는 출처 발언을 구조화한 정보 대시보드입니다. ‘적정가·목표가’와 ‘매수·진입가’는 원문에 명시된 경우만 표시하고, 없으면 명시 안 됨으로 둡니다. 실제 매매 전에는 현재가·공시·실적·수급을 별도로 확인해 주세요.</div>{section('domestic', common, items)}{section('global', common, items)}</main>
<footer>Generated by Hermes Stock Info Agent</footer>
</body></html>'''
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(doc, encoding='utf-8')
    print(f'Wrote {OUT} items={len(items)} common={len(common)}')


if __name__ == '__main__':
    main()
