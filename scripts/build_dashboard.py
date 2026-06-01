#!/usr/bin/env python3
import html
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'items.json'
COMMON = ROOT / 'data' / 'common_recommendations.json'
YSTATS = ROOT / 'data' / 'youtuber_stats.json'
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


def rec_card(rec, rank):
    count = len(rec.get('evidence', [])) or rec.get('source_count', 0)
    return f'''
    <div class="stock-rank-card">
      <span class="rank">#{rank}</span>
      <span class="stock-name">{esc(rec.get('name'))}</span>
      <span class="stock-code">{esc(rec.get('ticker'))}</span>
      <span class="mention-count"><b>{count}</b>번 거론</span>
    </div>'''


def youtuber_card(stat):
    stocks = stat.get('stocks', [])[:8]
    stock_html = ''.join(f'<span class="yt-stock">{esc(s.get("name"))} <b>{s.get("count",0)}</b>회</span>' for s in stocks) or '<span class="empty">거론 종목 없음</span>'
    transcript_count = stat.get('transcript_count', 0)
    video_count = stat.get('video_count', 0)
    precision = f'{transcript_count}/{video_count} 자막' if video_count else '자막 0'
    return f'''
    <article class="youtuber-card">
      <div class="yt-head"><h3>{esc(stat.get('youtuber'))}</h3><span>{video_count}개 영상</span></div>
      <div class="yt-quality"><span>{esc(precision)}</span><span>{stat.get('transcript_chars',0):,}자 분석</span></div>
      <div class="yt-count"><b>{stat.get('mention_count',0)}</b>번 거론</div>
      <div class="yt-stocks">{stock_html}</div>
    </article>'''


def youtuber_section(region, ystats):
    stats = [s for s in ystats if s.get('region') == region]
    stats = sorted(stats, key=lambda s: (s.get('mention_count', 0), s.get('video_count', 0)), reverse=True)
    html = ''.join(youtuber_card(s) for s in stats) or '<p class="empty">유튜버 통계가 아직 없습니다.</p>'
    return f'<h2>{LABEL[region]} 유튜버별 최신 10개 영상 통계</h2><div class="youtuber-grid">{html}</div>'


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


def section(region, common, items, ystats):
    recs = [rec for rec in common if rec.get('region') == region]
    recs = sorted(recs, key=lambda r: (len(r.get('evidence', [])), r.get('source_count', 0)), reverse=True)
    details = [item for item in items if item.get('region') == region]
    rec_html = '<div class="stock-rank-grid">' + '\n'.join(rec_card(rec, idx + 1) for idx, rec in enumerate(recs)) + '</div>' if recs else '<p class="empty">추천/관심 종목이 아직 없습니다.</p>'
    detail_html = '\n'.join(item_card(item) for item in details[:14]) or '<p class="empty">수집 항목이 없습니다.</p>'
    return f'<section id="{region}" class="tabpanel"><h2>{LABEL[region]} 종목 언급 순위</h2>{rec_html}{youtuber_section(region, ystats)}<h2>{LABEL[region]} 소스별 최신 발언</h2>{detail_html}</section>'


def main():
    items = load(DATA, [])
    common = load(COMMON, [])
    ystats = load(YSTATS, [])
    generated = datetime.now().strftime('%Y-%m-%d %H:%M')
    total_sources = len(set(item.get('source') for item in items))
    yt_items = [item for item in items if str(item.get('source_type','')).startswith('youtube')]
    transcript_items = [item for item in yt_items if item.get('confidence') == 'transcript']
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
.stock-rank-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;margin:12px 0 28px}} .stock-rank-card{{display:grid;grid-template-columns:auto 1fr auto;grid-template-areas:"rank name count" "rank code count";gap:2px 12px;align-items:center;background:linear-gradient(135deg,rgba(101,214,255,.14),rgba(18,26,51,.96));border:1px solid rgba(101,214,255,.28);border-radius:18px;padding:16px;box-shadow:0 10px 26px rgba(0,0,0,.22)}} .rank{{grid-area:rank;color:var(--yellow);font-weight:800;font-size:18px}} .stock-name{{grid-area:name;font-size:20px;font-weight:800;color:#fff}} .stock-code{{grid-area:code;color:var(--green);font-size:14px}} .mention-count{{grid-area:count;color:var(--yellow);white-space:nowrap}} .mention-count b{{font-size:28px}}
.youtuber-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px;margin:12px 0 30px}} .youtuber-card{{background:rgba(24,36,66,.92);border:1px solid rgba(137,247,165,.22);border-radius:18px;padding:16px;box-shadow:0 10px 26px rgba(0,0,0,.2)}} .yt-head{{display:flex;justify-content:space-between;gap:12px;align-items:start}} .yt-head h3{{margin:0;font-size:18px}} .yt-head span{{color:var(--muted);white-space:nowrap}} .yt-quality{{display:flex;gap:8px;flex-wrap:wrap;margin:9px 0 0}} .yt-quality span{{font-size:12px;color:var(--accent);border:1px solid rgba(101,214,255,.25);border-radius:999px;padding:4px 8px;background:rgba(101,214,255,.08)}} .yt-count{{margin:12px 0;color:var(--yellow)}} .yt-count b{{font-size:30px}} .yt-stocks{{display:flex;flex-wrap:wrap;gap:8px}} .yt-stock{{display:inline-flex;gap:5px;background:rgba(101,214,255,.09);border:1px solid rgba(101,214,255,.2);border-radius:999px;padding:6px 10px;color:#eaf3ff}} .yt-stock b{{color:var(--green)}}
.rec-head{{display:flex;justify-content:space-between;gap:16px}} .rec-head h3{{font-size:24px;margin:0 0 6px}} .ticker-text{{color:var(--green);font-size:18px}} .score{{text-align:right;color:var(--yellow);white-space:nowrap}} .score strong{{font-size:26px}} .stance{{margin:0;color:#eaf1ff}} .risk{{color:var(--red)!important}}
.summary-grid,.price-grid,.mini-price{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}} .summary-grid>div{{background:rgba(101,214,255,.07);border:1px solid rgba(101,214,255,.16);border-radius:14px;padding:12px}} .summary-grid p{{margin:6px 0 0}}
.evidence-list{{list-style:none;padding:0;margin:14px 0 0}} .evidence-row{{border-top:1px solid #26385f;padding:12px 0}} .ev-top{{display:flex;flex-wrap:wrap;gap:10px;align-items:center;color:#dbe7ff}} .ev-title{{margin-top:6px;color:#fff}} .ev-reason{{margin-top:8px;color:#d9e4ff;line-height:1.5}}
.meta{{display:flex;flex-wrap:wrap;gap:10px;font-size:14px}} a{{color:var(--accent)}} .badges{{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}} .badge{{display:inline-flex;padding:5px 10px;border-radius:999px;background:var(--panel2);color:#dbe7ff;font-size:13px}}
.ticker{{color:var(--green);border:1px solid rgba(137,247,165,.35)}} .rec{{color:var(--yellow);border:1px solid rgba(255,224,138,.35)}} .conf{{color:var(--accent)}} .meta-badge{{color:#cbd9ff}} .region{{color:#fff}} .type{{color:#c8b6ff}} footer{{color:var(--muted);text-align:center;padding:22px}}
@media (max-width:760px){{.summary-grid,.price-grid,.mini-price{{grid-template-columns:1fr}} .rec-head{{display:block}} .score{{text-align:left;margin-top:8px}}}}
</style></head>
<body>
<header><h1>종목추천 소스 대시보드</h1><div class="subtitle">상단에는 종목별 거론 횟수만 크게 보여주고, 아래에는 원문 발언 로그를 정리합니다. / 생성: {generated}</div><div class="kpis"><div class="kpi">수집 소스 {total_sources}개</div><div class="kpi">소스 로그 {len(items)}개</div><div class="kpi">추천/관심 종목 {len(common)}개</div><div class="kpi">유튜브 자막 {len(transcript_items)}/{len(yt_items)}개</div></div></header>
<nav class="tabs"><a href="#domestic">국내</a><a href="#global">해외</a></nav>
<main><div class="notice">이 페이지는 출처 발언을 구조화한 정보 대시보드입니다. 유튜버별 통계는 각 채널 최신 10개 영상에서 종목이 몇 번 거론됐는지 집계합니다. 실제 매매 전에는 현재가·공시·실적·수급을 별도로 확인해 주세요.</div>{section('domestic', common, items, ystats)}{section('global', common, items, ystats)}</main>
<footer>Generated by Hermes Stock Info Agent</footer>
</body></html>'''
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(doc, encoding='utf-8')
    print(f'Wrote {OUT} items={len(items)} common={len(common)}')


if __name__ == '__main__':
    main()
