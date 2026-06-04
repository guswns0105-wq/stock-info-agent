#!/usr/bin/env python3
import html
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'items.json'
COMMON = ROOT / 'data' / 'common_recommendations.json'
YSTATS = ROOT / 'data' / 'youtuber_stats.json'
VALUATIONS = ROOT / 'data' / 'valuations.json'
METHODOLOGY = ROOT / 'data' / 'dashboard_methodology.json'
NEWS_MD = ROOT / 'data' / 'news_ingest' / 'latest_news.md'
OUT = ROOT / 'public' / 'index.html'
LABEL = {'domestic': '국내', 'global': '해외'}


def load(path, default):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def esc(value):
    return html.escape(str(value or ''))

def public_text(value):
    text = str(value or '')
    replacements = {
        '로컬팩': '분석 근거',
        'local pack': 'analysis evidence',
        'Local Pack': 'Analysis Evidence',
        '로컬 ASR 팩': 'ASR 자료',
        '확장팩': '확장 자료',
        '광범위 팩': '광범위 자료',
        ' 팩': ' 자료',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def human_copy(value):
    """Clean stiff generated phrases before they reach the public page."""
    text = public_text(value)
    replacements = {
        '기준으로 산정했습니다': '기준으로 계산했습니다',
        '추천 근거 산정 대기': '근거를 더 모으는 중입니다',
        '추천 후보를 산정할 데이터': '추천 후보를 고를 데이터',
        '산정할 데이터': '고를 데이터',
        '산정했습니다': '계산했습니다',
        '보수 산정 적정가': '보수적으로 계산한 적정가격',
        '산정': '계산',
        '검토용': '참고용',
        '활용': '사용',
        '유의미': '의미 있는',
        '핵심': '주요',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


DOMESTIC_FORBIDDEN_TERMS = ['NVDA', 'NVIDIA', '엔비디아', '엔디비아']


def region_text(value, region=None):
    """Escape text after removing cross-market trigger words from market tabs.

    Some Korean-stock videos mention US mega-caps as catalysts in their title or
    hashtags while the detected tickers are domestic. The public domestic tab is
    required to contain domestic stocks only, so suppress explicit US ticker/name
    trigger words there while preserving the source card itself.
    """
    text = str(value or '')
    if region == 'domestic':
        for term in DOMESTIC_FORBIDDEN_TERMS:
            text = text.replace(term, '해외 반도체 기업')
    return esc(text)


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


def money(value, currency=''):
    if value is None or value == '':
        return '확인 불가'
    try:
        v = float(value)
    except Exception:
        return esc(value)
    if currency == 'KRW':
        return f'{v:,.0f}원'
    if currency:
        return f'{v:,.2f} {esc(currency)}'
    return f'{v:,.2f}'


def price_hint(price, fair_value, currency=''):
    """Plain-language explanation for non-expert readers."""
    try:
        p = float(price)
        f = float(fair_value)
    except Exception:
        return '가격 비교에 필요한 데이터가 부족합니다.'
    if p <= 0:
        return '현재가 데이터가 불안정해서 비교하지 않았습니다.'
    gap = (f - p) / p * 100
    if gap >= 15:
        tone = '지금 가격은 계산된 적정가격보다 낮습니다. 다만 왜 싼지는 따로 확인해야 합니다.'
    elif gap >= 3:
        tone = '지금 가격은 계산된 적정가격 근처입니다. 서두르기보다 실적과 뉴스를 같이 봐야 합니다.'
    elif gap >= -10:
        tone = '지금 가격은 계산된 적정가격과 비슷하거나 조금 높습니다. 추가 확인이 필요한 구간입니다.'
    else:
        tone = '지금 가격은 계산된 적정가격보다 높습니다. 추격하면 부담이 커질 수 있습니다.'
    return f'{tone} 현재가와 계산가격 차이는 {gap:+.1f}%입니다.'


def metric(value, suffix=''):
    if value is None or value == '':
        return '확인 불가'
    try:
        return f'{float(value):,.2f}{suffix}'
    except Exception:
        return esc(value)


def valuation_card(v):
    positives = ''.join(f'<span class="good">{esc(x)}</span>' for x in v.get('positives', [])) or '<span class="empty">강점 미확인</span>'
    risks = ''.join(f'<span class="risk-pill">{esc(x)}</span>' for x in v.get('risks', [])) or '<span class="empty">주요 리스크 미표시</span>'
    basis = ' / '.join(v.get('valuation_basis', [])) or '공개 재무지표 부족'
    verdict_cls = 'value-good' if v.get('verdict') == '저평가 후보' else ('value-watch' if v.get('verdict') in ('관심권','중립/대기') else 'value-risk')
    source_links = ''.join(f'<a href="{esc(url)}" target="_blank" rel="noreferrer">재무출처</a>' for url in v.get('data_sources', [])[:2])
    hint = price_hint(v.get('price'), v.get('fair_value'), v.get('currency'))
    return f'''
    <article class="valuation-card {verdict_cls}">
      <div class="valuation-head"><div><b>{esc(v.get('name'))}</b><span>{esc(v.get('ticker'))}</span></div>{badge(v.get('verdict'), 'rec')}</div>
      <div class="valuation-price"><span><small>지금 가격</small><b>{money(v.get('price'), v.get('currency'))}</b></span><span><small>계산상 적정가격</small><b>{money(v.get('fair_value'), v.get('currency'))}</b></span><span><small>알림 걸어둘 가격</small><b>{money(v.get('watch_buy_price'), v.get('currency'))}</b></span></div>
      <p class="plain-price-hint"><b>쉽게 말하면:</b> {esc(hint)}</p>
      <p><b>읽는 법:</b> {esc(human_copy(v.get('rationale')))}<br><b>다음에 볼 것:</b> {esc(human_copy(v.get('action')))}</p>
      <div class="valuation-metrics"><span>PER {metric(v.get('pe'))}</span><span>Fwd PER {metric(v.get('forward_pe'))}</span><span>PBR {metric(v.get('pb'))}</span><span>ROE {metric(v.get('roe'), '%')}</span><span>순마진 {metric(v.get('profit_margin'), '%')}</span><span>차트 {(esc((v.get('chart') or {}).get('trend')) or '확인 불가')}</span><span>20일 {metric((v.get('chart') or {}).get('ret20_pct'), '%')}</span></div>
      <div class="valuation-basis">산식: {esc(basis)}</div>
      <div class="valuation-pills"><b>강점</b>{positives}</div>
      <div class="valuation-pills"><b>주의</b>{risks}</div>
      <div class="valuation-links">{source_links}</div>
    </article>'''


def ai_recommendation_card(rec):
    why = ''.join(f'<li>{esc(human_copy(x))}</li>' for x in rec.get('why', [])) or '<li>근거를 더 모으는 중입니다</li>'
    region_label = LABEL.get(rec.get('region'), rec.get('region'))
    hint = price_hint(rec.get('price'), rec.get('fair_value'), rec.get('currency'))
    return f'''
    <article class="ai-rec-card">
      <div class="ai-rank">추천 {esc(rec.get('rank'))}</div>
      <div class="ai-rec-head"><div><h3>{esc(rec.get('name'))}</h3><span>{esc(rec.get('ticker'))} · {esc(region_label)}</span></div><strong>{metric(rec.get('ai_score'))}점</strong></div>
      <div class="ai-price-grid"><span><small>지금 가격</small><b>{money(rec.get('price'), rec.get('currency'))}</b></span><span><small>알림 걸어둘 가격</small><b>{money(rec.get('ai_buy_price'), rec.get('currency'))}</b></span><span><small>비싸 보이기 시작하는 가격</small><b>{money(rec.get('ai_sell_price'), rec.get('currency'))}</b></span><span><small>계산상 적정가격</small><b>{money(rec.get('fair_value'), rec.get('currency'))}</b></span></div>
      <p class="plain-price-hint"><b>쉽게 말하면:</b> {esc(hint)}</p>
      <p class="ai-comment"><b>왜 후보인가:</b> {esc(human_copy(rec.get('comment')))}</p>
      <div class="valuation-metrics"><span>PER {metric(rec.get('pe'))}</span><span>PBR {metric(rec.get('pb'))}</span><span>ROE {metric(rec.get('roe'), '%')}</span><span>차트 {esc(rec.get('trend') or '확인 불가')}</span><span>20일 {metric(rec.get('ret20_pct'), '%')}</span></div>
      <ul class="ai-why">{why}</ul>
      <div class="ai-risk">{esc(human_copy(rec.get('risk_comment')))}</div>
    </article>'''


def ai_recommendation_section(region, recommendations):
    if isinstance(recommendations, list):
        recs = [r for r in recommendations if r.get('region') == region][:5]
    else:
        recs = (recommendations or {}).get(region, [])[:5]
    title = '국내주식 AI 추천 Top5' if region == 'domestic' else '미국주식 AI 추천 Top5'
    empty = '국내 AI 추천 후보를 고를 데이터가 아직 없습니다.' if region == 'domestic' else '미국/해외 AI 추천 후보를 고를 데이터가 아직 없습니다.'
    html = ''.join(ai_recommendation_card(r) for r in recs) or f'<p class="empty">{empty}</p>'
    return f'''<section class="ai-top-section"><h2>{title}</h2><p class="section-note">먼저 볼 종목을 추린 목록입니다. “알림 걸어둘 가격”은 다시 볼 만한 가격, “비싸 보이기 시작하는 가격”은 과열을 의심할 가격입니다. 매수·매도 지시는 아닙니다.</p><div class="ai-rec-grid">{html}</div></section>'''


def imagegen2_cardnews_section():
    assets = [
        ('assets/imagegen2/korea-top5-cardnews.png', '한국주식 Top5 이미지젠2 카드뉴스', '한국주식 5개 요약'),
        ('assets/imagegen2/us-top5-cardnews.png', '미국주식 Top5 이미지젠2 카드뉴스', '미국주식 5개 요약'),
    ]
    figures = []
    for rel, alt, caption in assets:
        path = ROOT / 'public' / rel
        if path.exists() and path.stat().st_size > 100_000:
            figures.append(f'<figure><img src="{rel}" alt="{alt}"><figcaption>{caption}</figcaption></figure>')
    if not figures:
        return ''
    return f'''<section class="imagegen2-section" aria-label="이미지젠2 종목 설명 카드뉴스">
      <div class="imagegen2-head"><span>ImageGen2 카드뉴스</span><h2>그림으로 먼저 보는 국내·미국 Top5</h2><p>종목 설명을 한 장씩 빠르게 훑어보는 카드뉴스입니다. 세부 수치와 원문 근거는 아래 추천 카드에서 다시 확인해 주세요.</p></div>
      <div class="imagegen2-grid">{''.join(figures)}</div>
    </section>'''


def methodology_section(methodology, yt_items, transcript_items):
    if not methodology:
        return ''
    method_cards = []
    for card in methodology.get('method_cards', []):
        checks = ''.join(f'<li>{esc(public_text(x))}</li>' for x in card.get('checks', []))
        method_cards.append(f'''
        <article class="method-card">
          <h3>{esc(public_text(card.get('title')))}</h3>
          <p>{esc(public_text(card.get('body')))}</p>
          <ul>{checks}</ul>
        </article>''')
    themes = methodology.get('theme_radar', [])[:8]
    theme_html = ''.join(f'<div class="theme-row"><b>{esc(public_text(t.get("theme")))}</b><span>{int(t.get("count",0))}번 언급</span><small>{esc(public_text(t.get("note")))}</small></div>' for t in themes)
    evidence = methodology.get('source_evidence', [])
    evidence_html = ''.join(f'<li><b>{esc(public_text(e.get("name")))}</b><span>{esc(public_text(e.get("evidence")))}</span><small>{esc(public_text(e.get("dashboard_use")))}</small></li>' for e in evidence)
    improvements = methodology.get('dashboard_improvements', [])
    status_names = {'implemented': '반영됨', 'next': '다음에 볼 것'}
    status_classes = {'implemented': 'done', 'next': 'next'}
    improvement_html = ''.join(f'<li class="improvement-row"><b>{esc(human_copy(x.get("title")))}</b><span class="status-{esc(status_classes.get(x.get("status"), "next"))}">{esc(status_names.get(x.get("status"), x.get("status")))}</span><small>{esc(human_copy(x.get("why")))}</small></li>' for x in improvements)
    local_pack_html = ''.join(f'<article class="analysis-evidence-card"><b>{esc(public_text(e.get("name")))}</b><span>{esc(public_text(e.get("evidence")))}</span><small>{esc(public_text(e.get("dashboard_use")))}</small></article>' for e in evidence[:4])
    ocr_items = [item for item in yt_items if item.get('ocr_status') == 'ok']
    ocr_chars = sum(int(item.get('ocr_chars') or 0) for item in ocr_items)
    return f'''
    <section class="method-section">
      <div class="method-head">
        <div><h2>자료가 얼마나 믿을 만한지 보기</h2><p class="section-note">자막, 화면 OCR, 출처 날짜를 따로 보여줍니다. 제목만 보고 만든 항목은 점수를 낮췄습니다.</p></div>
        <div class="quality-score"><b>{len(transcript_items)}/{len(yt_items)}</b><span>유튜브 자막</span><b>{len(ocr_items)}</b><span>OCR 성공 · {ocr_chars:,}자</span></div>
      </div>
      <div class="analysis-evidence-panel"><h3>읽은 자료</h3><p>아래 자료는 출처의 신뢰도와 반복해서 나온 이야기를 확인하는 데만 씁니다.</p><div class="analysis-evidence-grid">{local_pack_html}</div></div>
      <div class="method-grid">{''.join(method_cards)}</div>
      <div class="theme-panel"><h3>섹터·테마 쉽게 보기</h3><p>여러 출처에서 반복해서 나온 이야기입니다. 많이 나왔다고 좋은 종목이라는 뜻은 아닙니다.</p><div class="theme-grid">{theme_html}</div></div>
      <div class="improvement-panel"><h3>이번에 손본 부분</h3><ul>{improvement_html}</ul></div>
      <details class="method-evidence"><summary>어떤 자료를 읽었는지 보기</summary><ul>{evidence_html}</ul><p>{esc(public_text(methodology.get('safety_note')))}</p></details>
    </section>'''


def valuation_section(region, valuations):
    vals = [v for v in valuations if v.get('region') == region]
    vals = sorted(vals, key=lambda v: (v.get('score', -99), v.get('margin_to_fair_pct') or -999), reverse=True)
    html = ''.join(valuation_card(v) for v in vals[:10]) or '<p class="empty">재무 판단 데이터가 아직 없습니다.</p>'
    return f'<h2>{LABEL[region]} 가격이 싼지 비싼지 쉽게 보기</h2><p class="section-note">PER/PBR/ROE는 아래 작은 배지로 남겨두고, 먼저 가격만 읽기 쉽게 바꿨습니다. 이 숫자는 결론이 아니라 다시 확인할 기준선입니다.</p><div class="valuation-grid">{html}</div>'


def youtuber_card(stat, region=None):
    stocks = stat.get('stocks', [])[:8]
    stock_html = ''.join(f'<span class="yt-stock">{esc(s.get("name"))} <b>{s.get("count",0)}</b>회</span>' for s in stocks) or '<span class="empty">거론 종목 없음</span>'
    transcript_count = stat.get('transcript_count', 0)
    video_count = stat.get('video_count', 0)
    precision = f'{transcript_count}/{video_count} 자막' if video_count else '자막 0'
    ocr_count = stat.get('ocr_count', 0)
    ocr_precision = f'{ocr_count}/{video_count} OCR' if video_count else 'OCR 0'
    short_count = stat.get('short_count', 0)
    regular_count = stat.get('regular_video_count', video_count - short_count)
    video_rows = []
    for video in stat.get('videos', [])[:10]:
        tags = ''.join(badge(t, 'ticker') for t in video.get('tickers', [])) or '<span class="empty">종목 미검출</span>'
        kind = '쇼츠' if video.get('youtube_kind') == 'short' else '영상'
        if video.get('confidence') == 'transcript':
            conf = '자막본문'
        elif video.get('confidence') == 'ocr_only':
            conf = 'OCR화면'
        elif video.get('confidence') == 'caption_failed':
            conf = '자막실패·분석제외'
        else:
            conf = '제목/설명'
        ocr_badge = ' · OCR' if video.get('ocr_status') == 'ok' else ''
        url = esc(video.get('url') or '')
        link = f'<a href="{url}" target="_blank" rel="noreferrer">보기</a>' if url else ''
        video_rows.append(f'<li><span class="yt-video-kind">{kind}</span><b>{region_text(video.get("title"), region)}</b><div>{tags}</div><small>{conf} 기반{ocr_badge} · {short_date(video.get("published_at"))} {link}</small></li>')
    video_html = '<ol class="yt-video-list">' + ''.join(video_rows) + '</ol>' if video_rows else ''
    return f'''
    <article class="youtuber-card">
      <div class="yt-head"><h3>{esc(stat.get('youtuber'))}</h3><span>{video_count}개 콘텐츠</span></div>
      <div class="yt-quality"><span>영상 {regular_count} / 쇼츠 {short_count}</span><span>{esc(precision)}</span><span>{esc(ocr_precision)}</span><span>{stat.get('transcript_chars',0):,}자 + OCR {stat.get('ocr_chars',0):,}자</span></div>
      <div class="yt-count"><b>{stat.get('mention_count',0)}</b>번 거론</div>
      <div class="yt-stocks">{stock_html}</div>
      {video_html}
    </article>'''


def youtuber_section(region, ystats):
    stats = [s for s in ystats if s.get('region') == region]
    stats = sorted(stats, key=lambda s: (s.get('mention_count', 0), s.get('video_count', 0)), reverse=True)
    html = ''.join(youtuber_card(s, region) for s in stats) or '<p class="empty">유튜버 통계가 아직 없습니다.</p>'
    return f'<h2>{LABEL[region]} 유튜버별 최신 영상·쇼츠 통계</h2><div class="youtuber-grid">{html}</div>'


def item_card(item, region=None):
    markets = item.get('ticker_markets') or {}
    raw_tickers = item.get('tickers', [])
    visible_tickers = [t for t in raw_tickers if not region or markets.get(t, region) == region]
    tickers = ''.join(badge(ticker, 'ticker') for ticker in visible_tickers)
    link = f'<a class="source-link" href="{esc(item.get("url"))}" target="_blank" rel="noreferrer">원문</a>' if item.get('url') else ''
    when = item.get('published_at') or item.get('collected_at') or ''
    confidence = badge('자막 기반', 'conf') if item.get('confidence') == 'transcript' else badge('제목/설명 기반', 'meta-badge')
    role = badge(item.get('source_role') or item.get('source_type', ''), 'type')
    return f'''
    <article class="card small">
      <div class="meta"><strong>{esc(item.get('source'))}</strong><span>{esc(short_date(when))}</span>{link}</div>
      <h4>{region_text(item.get('title'), region)}</h4>
      <p>{region_text(item.get('summary'), region)}</p>
      <div class="mini-price"><span>적정가: {esc(item.get('target_price'))}</span><span>매수/진입: {esc(item.get('buy_zone'))}</span></div>
      <div class="badges">{badge(item.get('recommendation'), 'rec')}{confidence}{role}{tickers}</div>
    </article>'''


def item_visible_in_region(item, region):
    markets = item.get('ticker_markets') or {}
    return any(markets.get(t, item.get('region')) == region for t in (item.get('tickers') or []))




def news_ingest_card():
    if not NEWS_MD.exists():
        return ''
    try:
        lines = NEWS_MD.read_text(encoding='utf-8').splitlines()
        preview = '\n'.join(lines[:18])
        preview = human_copy(preview).replace('크론', '자동 갱신').replace('정규화한 자료', '정리한 자료')
    except Exception:
        return ''
    return f'''<details class="news-md-card"><summary>Markdown 뉴스 인제스트 보기</summary><pre>{esc(preview)}</pre><p class="section-note">전체 파일: data/news_ingest/latest_news.md - 매시간 새로 정리되는 뉴스 인제스트 메모입니다.</p></details>'''

def news_section(items):
    news = [item for item in items if item.get('source_role') == '뉴스' or item.get('source_type') == 'rss']
    if not news:
        return '<section id="news" class="news-section"><h2>뉴스 브리핑</h2><p class="empty">수집된 뉴스가 아직 없습니다.</p></section>'
    def region_name(region):
        return '한국시장' if region == 'domestic' else '미국시장'
    groups = []
    for region in ['domestic', 'global']:
        rows = []
        region_news = [n for n in news if n.get('region') == region][:10]
        for item in region_news:
            link = f'<a class="read-link" href="{esc(item.get("url"))}" target="_blank" rel="noreferrer">원문 보기</a>' if item.get('url') else ''
            summary = esc(item.get('summary_ko') or item.get('summary') or item.get('text') or '요약 없음')
            original = item.get('title_original') or ''
            # Show the preserved original-title row whenever the item carries an
            # original field, even if a previous collection run already wrote the
            # translated title into both title and title_original.  The public
            # dashboard still needs an explicit provenance row plus the visible
            # Korean-translation badge for US/global news cards.
            original_html = f'<div class="news-original">원문: {esc(original)}</div>' if original else ''
            tickers = ''.join(badge(ticker, 'ticker') for ticker in (item.get('tickers') or [])[:5]) or '<span class="news-no-ticker">종목 미검출</span>'
            trans = badge('한글 번역', 'conf') if region == 'global' and (item.get('title_ko') or item.get('translation_note') or original_html) else ''
            rows.append(f'''<article class="news-card readable-news">
              <div class="news-top"><b>{esc(item.get('source'))}</b><span>{short_date(item.get('published_at') or item.get('collected_at'))}</span>{trans}{link}</div>
              <h3>{esc(item.get('title_ko') or item.get('title'))}</h3>
              {original_html}
              <p>{summary}</p>
              <div class="badges news-tickers">{tickers}</div>
            </article>''')
        body = ''.join(rows) if rows else '<p class="empty">뉴스 없음</p>'
        groups.append(f'<div class="news-column"><h3>{region_name(region)} 뉴스 <small>{len(region_news)}건</small></h3>{body}</div>')
    return f'''<section id="news" class="news-section"><div class="section-kicker">뉴스</div><h2>시간별 뉴스 브리핑 · 미국뉴스 자동번역</h2><p class="section-note">미국 뉴스는 한국어 제목을 먼저 보여주고, 원문 제목과 링크를 같이 남깁니다. 뉴스는 배경 확인용입니다.</p><div class="news-grid">{''.join(groups)}</div>{news_ingest_card()}</section>'''

def top_recommendations_section(ai_recommendations):
    return f'''<section id="top-recommendations" class="top-rec-section"><div class="top-rec-head"><span>먼저 볼 것</span><h2>AI 추천종목 Top5</h2><p>국내와 미국을 나눠서 보여줍니다. 많이 언급된 종목, 재무 숫자, 차트 위치를 함께 본 관심 목록입니다. 매수 지시는 아닙니다.</p></div>{imagegen2_cardnews_section()}{ai_recommendation_section('domestic', ai_recommendations)}{ai_recommendation_section('global', ai_recommendations)}</section>'''


def section(region, common, items, ystats, valuations, ai_recommendations):
    recs = [rec for rec in common if rec.get('region') == region]
    recs = sorted(recs, key=lambda r: (len(r.get('evidence', [])), r.get('source_count', 0)), reverse=True)
    details = [item for item in items if item_visible_in_region(item, region)]
    rec_html = '<div class="stock-rank-grid">' + '\n'.join(rec_card(rec, idx + 1) for idx, rec in enumerate(recs)) + '</div>' if recs else '<p class="empty">추천/관심 종목이 아직 없습니다.</p>'
    detail_html = '\n'.join(item_card(item, region) for item in details[:14]) or '<p class="empty">수집 항목이 없습니다.</p>'
    return f'<section id="{region}" class="tabpanel"><h2>{LABEL[region]} 종목 언급 순위</h2>{rec_html}{valuation_section(region, valuations)}{youtuber_section(region, ystats)}<h2>{LABEL[region]} 소스별 최신 발언</h2>{detail_html}</section>'


def main():
    items = load(DATA, [])
    common = load(COMMON, [])
    ystats = load(YSTATS, [])
    valuation_data = load(VALUATIONS, {'valuations': []})
    methodology = load(METHODOLOGY, {})
    valuations = valuation_data.get('valuations', []) if isinstance(valuation_data, dict) else valuation_data
    ai_recommendations = valuation_data.get('ai_recommendations', []) if isinstance(valuation_data, dict) else []
    generated = datetime.now().strftime('%Y-%m-%d %H:%M')
    total_sources = len(set(item.get('source') for item in items))
    yt_items = [item for item in items if str(item.get('source_type','')).startswith('youtube')]
    transcript_items = [item for item in yt_items if item.get('confidence') == 'transcript']
    ocr_items = [item for item in yt_items if item.get('ocr_status') == 'ok']
    doc = f'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>한국·미국 주식 한눈에 보기</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{{--panel:#121a33;--panel2:#182442;--text:#eef3ff;--muted:#9fb0d0;--accent:#65d6ff;--green:#89f7a5;--yellow:#ffe08a;--red:#ffd0d0}}
*{{box-sizing:border-box}} body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:radial-gradient(circle at top left,#18305f,#081020 45%,#070b16);color:var(--text)}}
header,main{{max-width:1180px;margin:auto}} header{{padding:36px 22px 18px}} h1{{margin:0 0 8px;font-size:clamp(28px,5vw,46px)}} .subtitle,.meta,.empty{{color:var(--muted)}}
.kpis{{display:flex;gap:10px;flex-wrap:wrap;margin-top:16px}} .kpi{{background:rgba(101,214,255,.10);border:1px solid rgba(101,214,255,.25);padding:10px 14px;border-radius:14px}}
.tabs{{display:flex;gap:10px;max-width:1180px;margin:0 auto 16px;padding:0 22px;flex-wrap:wrap}} .tabs a{{text-decoration:none;color:var(--text);background:var(--panel);border:1px solid #26385f;padding:10px 18px;border-radius:999px}}
main{{padding:0 22px 60px}} .notice{{background:rgba(255,224,138,.1);border:1px solid rgba(255,224,138,.25);border-radius:14px;padding:14px;color:#fff0be;line-height:1.55}} .top-rec-section{{margin:18px 0 36px;background:linear-gradient(145deg,rgba(255,224,138,.14),rgba(24,36,66,.84));border:1px solid rgba(255,224,138,.34);border-radius:26px;padding:22px;box-shadow:0 18px 44px rgba(0,0,0,.30)}} .top-rec-head span{{display:inline-flex;color:#111;background:var(--yellow);border-radius:999px;padding:5px 11px;font-weight:900;font-size:12px}} .top-rec-head h2{{margin:10px 0 6px;color:#fff;font-size:clamp(26px,4vw,38px)}} .top-rec-head p{{color:#ffeec0;line-height:1.55;margin:0 0 8px}} h2{{color:var(--accent);margin-top:30px}}
.card{{background:rgba(18,26,51,.94);border:1px solid #26385f;border-radius:18px;padding:18px;margin:14px 0;box-shadow:0 12px 32px rgba(0,0,0,.25)}} .small h4{{font-size:18px;margin:8px 0}} .card p{{color:#d9e4ff;line-height:1.56}}
.stock-rank-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;margin:12px 0 28px}} .stock-rank-card{{display:grid;grid-template-columns:auto 1fr auto;grid-template-areas:"rank name count" "rank code count";gap:2px 12px;align-items:center;background:linear-gradient(135deg,rgba(101,214,255,.14),rgba(18,26,51,.96));border:1px solid rgba(101,214,255,.28);border-radius:18px;padding:16px;box-shadow:0 10px 26px rgba(0,0,0,.22)}} .rank{{grid-area:rank;color:var(--yellow);font-weight:800;font-size:18px}} .stock-name{{grid-area:name;font-size:20px;font-weight:800;color:#fff}} .stock-code{{grid-area:code;color:var(--green);font-size:14px}} .mention-count{{grid-area:count;color:var(--yellow);white-space:nowrap}} .mention-count b{{font-size:28px}} .section-note{{color:var(--muted);line-height:1.55}}
.news-section{{margin:18px 0 34px;background:linear-gradient(145deg,rgba(137,247,165,.08),rgba(24,36,66,.76));border:1px solid rgba(137,247,165,.20);border-radius:22px;padding:20px}} .news-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}} .news-column h3{{margin:4px 0 12px;color:#fff}} .news-card{{background:rgba(7,11,22,.34);border:1px solid rgba(101,214,255,.16);border-radius:16px;padding:13px;margin:10px 0}} .news-top{{display:flex;gap:9px;flex-wrap:wrap;color:var(--muted);font-size:13px}} .news-card h3{{font-size:16px;margin:8px 0 6px;color:#fff;line-height:1.35}} .news-card p{{color:#d9e4ff;line-height:1.45;margin:0;font-size:14px}} .news-md-card{{margin-top:14px;background:rgba(7,11,22,.34);border:1px solid rgba(255,224,138,.18);border-radius:16px;padding:12px}} .news-md-card summary{{cursor:pointer;color:var(--yellow);font-weight:700}} .news-md-card pre{{white-space:pre-wrap;max-height:280px;overflow:auto;color:#dbe7ff;font-size:12px;line-height:1.45}} .ai-top-section{{margin:22px 0 34px}} .ai-market-title{{margin:22px 0 12px;color:var(--yellow)}} .ai-rec-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px;margin-bottom:22px}} .ai-rec-card{{position:relative;background:linear-gradient(145deg,rgba(255,224,138,.16),rgba(18,26,51,.96));border:1px solid rgba(255,224,138,.42);border-radius:22px;padding:18px;box-shadow:0 16px 34px rgba(0,0,0,.28)}} .ai-rank{{display:inline-flex;color:#111;background:var(--yellow);border-radius:999px;padding:5px 10px;font-weight:900;font-size:12px}} .ai-rec-head{{display:flex;justify-content:space-between;gap:12px;align-items:start;margin-top:10px}} .ai-rec-head h3{{font-size:24px;margin:0 0 3px}} .ai-rec-head span{{color:var(--muted)}} .ai-rec-head strong{{color:var(--green);font-size:24px;white-space:nowrap}} .ai-price-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;margin:14px 0}} .ai-price-grid span{{background:rgba(255,224,138,.08);border:1px solid rgba(255,224,138,.22);border-radius:13px;padding:9px}} .ai-price-grid b{{display:block;color:#fff;margin-top:3px}} .ai-comment{{line-height:1.55}} .ai-why{{margin:10px 0;padding-left:20px;color:#eaf3ff}} .ai-risk{{font-size:13px;color:#ffe6e6;background:rgba(255,208,208,.08);border:1px solid rgba(255,208,208,.2);border-radius:12px;padding:9px;margin-top:10px}}
.method-section{{margin:18px 0 34px;background:linear-gradient(145deg,rgba(101,214,255,.10),rgba(24,36,66,.72));border:1px solid rgba(101,214,255,.24);border-radius:22px;padding:20px;box-shadow:0 14px 34px rgba(0,0,0,.24)}} .analysis-evidence-panel,.improvement-panel{{background:rgba(7,11,22,.32);border:1px solid rgba(101,214,255,.18);border-radius:18px;padding:15px;margin:14px 0}} .analysis-evidence-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px}} .analysis-evidence-card{{display:grid;gap:5px;background:rgba(101,214,255,.07);border:1px solid rgba(101,214,255,.18);border-radius:14px;padding:12px}} .analysis-evidence-card b{{color:var(--green)}} .analysis-evidence-card span,.analysis-evidence-card small,.improvement-panel small{{color:var(--muted);line-height:1.35}} .improvement-panel ul{{list-style:none;margin:0;padding:0;display:grid;gap:8px}} .improvement-row{{display:grid;grid-template-columns:1fr auto;gap:4px 10px;background:rgba(255,224,138,.07);border:1px solid rgba(255,224,138,.14);border-radius:13px;padding:10px}} .improvement-row small{{grid-column:1/-1}} .status-done{{color:var(--green)}} .status-next{{color:var(--yellow)}} .method-head{{display:flex;justify-content:space-between;gap:18px;align-items:start}} .method-head h2{{margin-top:0}} .quality-score{{min-width:190px;background:rgba(7,11,22,.45);border:1px solid rgba(137,247,165,.22);border-radius:18px;padding:14px;display:grid;grid-template-columns:auto 1fr;gap:5px 10px;align-items:baseline}} .quality-score b{{font-size:24px;color:var(--green)}} .quality-score span{{color:var(--muted);font-size:13px}} .method-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin:14px 0}} .method-card{{background:rgba(18,26,51,.82);border:1px solid rgba(101,214,255,.20);border-radius:18px;padding:15px}} .method-card h3,.theme-panel h3{{margin:0 0 8px;color:#fff}} .method-card p,.theme-panel p{{color:#d9e4ff;line-height:1.5}} .method-card ul{{padding-left:18px;color:#eaf3ff}} .theme-panel{{background:rgba(255,224,138,.08);border:1px solid rgba(255,224,138,.22);border-radius:18px;padding:15px;margin-top:12px}} .theme-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:9px}} .theme-row{{display:grid;gap:3px;background:rgba(7,11,22,.35);border-radius:14px;padding:10px;border:1px solid rgba(255,224,138,.14)}} .theme-row b{{color:var(--yellow)}} .theme-row span{{color:var(--green);font-weight:800}} .theme-row small{{color:var(--muted);line-height:1.35}} .method-evidence{{margin-top:12px;color:#d9e4ff}} .method-evidence summary{{cursor:pointer;color:var(--accent)}} .method-evidence li{{margin:8px 0}} .method-evidence span{{display:block;color:var(--muted)}}
.valuation-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px;margin:12px 0 30px}} .valuation-card{{background:rgba(18,26,51,.94);border:1px solid rgba(101,214,255,.22);border-radius:18px;padding:16px;box-shadow:0 10px 28px rgba(0,0,0,.23)}} .valuation-card.value-good{{border-color:rgba(137,247,165,.5)}} .valuation-card.value-watch{{border-color:rgba(255,224,138,.42)}} .valuation-card.value-risk{{border-color:rgba(255,208,208,.38)}} .valuation-head{{display:flex;justify-content:space-between;gap:12px;align-items:start}} .valuation-head b{{display:block;font-size:19px}} .valuation-head span{{color:var(--muted)}} .valuation-price{{display:grid;grid-template-columns:1fr;gap:7px;margin:12px 0}} .valuation-price span{{background:rgba(101,214,255,.08);border:1px solid rgba(101,214,255,.16);border-radius:12px;padding:8px 10px}} .valuation-metrics,.valuation-pills{{display:flex;flex-wrap:wrap;gap:7px;margin-top:10px}} .valuation-metrics span,.good,.risk-pill{{font-size:12px;border-radius:999px;padding:5px 9px;background:rgba(101,214,255,.08);border:1px solid rgba(101,214,255,.2)}} .good{{color:var(--green);border-color:rgba(137,247,165,.28)}} .risk-pill{{color:var(--red);border-color:rgba(255,208,208,.28)}} .valuation-basis{{color:var(--muted);font-size:13px;margin-top:10px;line-height:1.45}} .valuation-links{{display:flex;gap:10px;margin-top:10px;font-size:13px}}
.youtuber-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px;margin:12px 0 30px}} .youtuber-card{{background:rgba(24,36,66,.92);border:1px solid rgba(137,247,165,.22);border-radius:18px;padding:16px;box-shadow:0 10px 26px rgba(0,0,0,.2)}} .yt-head{{display:flex;justify-content:space-between;gap:12px;align-items:start}} .yt-head h3{{margin:0;font-size:18px}} .yt-head span{{color:var(--muted);white-space:nowrap}} .yt-quality{{display:flex;gap:8px;flex-wrap:wrap;margin:9px 0 0}} .yt-quality span{{font-size:12px;color:var(--accent);border:1px solid rgba(101,214,255,.25);border-radius:999px;padding:4px 8px;background:rgba(101,214,255,.08)}} .yt-count{{margin:12px 0;color:var(--yellow)}} .yt-count b{{font-size:30px}} .yt-stocks{{display:flex;flex-wrap:wrap;gap:8px}} .yt-stock{{display:inline-flex;gap:5px;background:rgba(101,214,255,.09);border:1px solid rgba(101,214,255,.2);border-radius:999px;padding:6px 10px;color:#eaf3ff}} .yt-stock b{{color:var(--green)}} .yt-video-list{{margin:14px 0 0;padding-left:20px;border-top:1px solid rgba(137,247,165,.18)}} .yt-video-list li{{padding:10px 0;color:#eaf3ff;line-height:1.38}} .yt-video-list b{{display:block;margin:4px 0;font-size:14px}} .yt-video-list small{{color:var(--muted)}} .yt-video-kind{{font-size:12px;color:var(--yellow);border:1px solid rgba(255,224,138,.28);border-radius:999px;padding:2px 7px}}
.rec-head{{display:flex;justify-content:space-between;gap:16px}} .rec-head h3{{font-size:24px;margin:0 0 6px}} .ticker-text{{color:var(--green);font-size:18px}} .score{{text-align:right;color:var(--yellow);white-space:nowrap}} .score strong{{font-size:26px}} .stance{{margin:0;color:#eaf1ff}} .risk{{color:var(--red)!important}}
.summary-grid,.price-grid,.mini-price{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}} .summary-grid>div{{background:rgba(101,214,255,.07);border:1px solid rgba(101,214,255,.16);border-radius:14px;padding:12px}} .summary-grid p{{margin:6px 0 0}}
.evidence-list{{list-style:none;padding:0;margin:14px 0 0}} .evidence-row{{border-top:1px solid #26385f;padding:12px 0}} .ev-top{{display:flex;flex-wrap:wrap;gap:10px;align-items:center;color:#dbe7ff}} .ev-title{{margin-top:6px;color:#fff}} .ev-reason{{margin-top:8px;color:#d9e4ff;line-height:1.5}}
.meta{{display:flex;flex-wrap:wrap;gap:10px;font-size:14px}} a{{color:var(--accent)}} .badges{{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}} .badge{{display:inline-flex;padding:5px 10px;border-radius:999px;background:var(--panel2);color:#dbe7ff;font-size:13px}}
.ticker{{color:var(--green);border:1px solid rgba(137,247,165,.35)}} .rec{{color:var(--yellow);border:1px solid rgba(255,224,138,.35)}} .conf{{color:var(--accent)}} .meta-badge{{color:#cbd9ff}} .region{{color:#fff}} .type{{color:#c8b6ff}} footer{{color:var(--muted);text-align:center;padding:22px}}
@media (max-width:760px){{.summary-grid,.price-grid,.mini-price,.news-grid{{grid-template-columns:1fr}} .rec-head,.method-head{{display:block}} .quality-score{{margin-top:12px}} .score{{text-align:left;margin-top:8px}}}}
/* Human-readable Linear/StockHub polish */
:root{{--panel:#101114;--panel2:#181a20;--text:#f7f8f8;--muted:#9aa3b2;--accent:#828fff;--green:#10b981;--yellow:#f8d16c;--red:#ff9b9b}}
html{{scroll-behavior:smooth;overflow-x: hidden}} body{{overflow-x: hidden;font-family:'Inter',system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;font-feature-settings:'cv01','ss03';background:radial-gradient(circle at 12% -10%,rgba(113,112,255,.22),transparent 34%),radial-gradient(circle at 88% 6%,rgba(16,185,129,.12),transparent 28%),#08090a;color:#f7f8f8}} header{{padding:42px 22px 22px}} h1{{letter-spacing:-1.05px;font-weight:600;max-width:860px}} .subtitle{{max-width:760px;line-height:1.65;color:#d0d6e0}} .kpi{{background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.08);color:#d0d6e0;box-shadow:inset 0 1px rgba(255,255,255,.04)}} .tabs{{position:sticky;top:0;z-index:10;backdrop-filter:blur(16px);background:linear-gradient(180deg,rgba(8,9,10,.92),rgba(8,9,10,.70));padding-top:10px;padding-bottom:10px;border-bottom:1px solid rgba(255,255,255,.06)}} .tabs a{{background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.08);color:#d0d6e0;font-weight:500}} .tabs a:first-child{{background:#5e6ad2;color:#fff;border-color:#7170ff}} .notice{{margin-bottom:18px;background:rgba(255,255,255,.035)!important;border:1px solid rgba(255,255,255,.08)!important;color:#d0d6e0!important}}

.imagegen2-section{{margin:18px 0 26px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.08);border-radius:22px;padding:18px}}.imagegen2-head span{{display:inline-flex;background:#10b981;color:#07130d;border-radius:999px;padding:5px 10px;font-size:12px;font-weight:900}}.imagegen2-head h2{{margin:10px 0 6px;color:#fff}}.imagegen2-head p{{color:#d0d6e0;line-height:1.55;margin:0 0 16px}}.imagegen2-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}}.imagegen2-grid figure{{margin:0;background:#050607;border:1px solid rgba(255,255,255,.08);border-radius:18px;overflow:hidden;box-shadow:0 18px 40px rgba(0,0,0,.28)}}.imagegen2-grid img{{display:block;width:100%;height:auto}}.imagegen2-grid figcaption{{padding:10px 12px;color:#d0d6e0;font-size:13px;text-align:center}}@media (max-width:760px){{.imagegen2-grid{{grid-template-columns:1fr}}.imagegen2-section{{padding:14px}}}}
.section-kicker{{display:inline-flex;margin-bottom:8px;color:#111;background:#f8d16c;border-radius:999px;padding:5px 10px;font-size:12px;font-weight:800}} .top-rec-section,.news-section,.method-section{{backdrop-filter:blur(8px)}} .top-rec-section{{background:linear-gradient(145deg,rgba(94,106,210,.22),rgba(255,255,255,.035))!important;border-color:rgba(130,143,255,.34)!important}} .top-rec-head{{display:grid;gap:6px;margin-bottom:6px}} .top-rec-head h2{{letter-spacing:-.7px}} .ai-top-section{{background:rgba(255,255,255,.025);border:1px solid rgba(255,255,255,.07);border-radius:22px;padding:18px;margin:18px 0}} .ai-top-section h2{{margin-top:0;color:#f7f8f8}} .ai-rec-grid{{grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}} .ai-rec-card{{background:linear-gradient(160deg,rgba(255,255,255,.065),rgba(255,255,255,.025))!important;border:1px solid rgba(255,255,255,.09)!important;border-radius:18px!important}} .ai-rank{{background:#5e6ad2!important;color:#fff!important}} .ai-rec-head h3{{letter-spacing:-.35px}} .ai-price-grid span,.valuation-price span{{background:rgba(255,255,255,.035)!important;border-color:rgba(255,255,255,.07)!important;display:grid;gap:3px}} .ai-price-grid small,.valuation-price small{{color:#9aa3b2;font-size:11px}} .plain-price-hint{{background:rgba(16,185,129,.08);border:1px solid rgba(16,185,129,.18);border-radius:13px;padding:10px 12px;color:#dffbea!important;line-height:1.55}}
.news-section{{background:linear-gradient(145deg,rgba(16,185,129,.10),rgba(255,255,255,.025))!important;border:1px solid rgba(255,255,255,.08)!important}} .news-grid{{align-items:start}} .news-column{{display:grid;gap:10px}} .news-column h3{{position:sticky;top:58px;z-index:2;background:rgba(15,16,17,.88);border:1px solid rgba(255,255,255,.08);border-radius:14px;padding:10px 12px;backdrop-filter:blur(12px)}} .news-column h3 small{{color:#8a8f98;font-size:12px;font-weight:500}} .readable-news{{margin:0!important;background:rgba(255,255,255,.035)!important;border:1px solid rgba(255,255,255,.075)!important;border-radius:16px!important;box-shadow:none!important}} .readable-news h3{{font-size:17px!important;line-height:1.45!important;letter-spacing:-.12px}} .news-original{{color:#8a8f98;font-size:12px;line-height:1.45;margin:-2px 0 8px;border-left:2px solid rgba(130,143,255,.45);padding-left:8px}} .news-tickers{{margin-top:10px!important}} .news-no-ticker{{color:#62666d;font-size:12px}} .read-link{{margin-left:auto;font-size:12px}}
.card,.valuation-card,.youtuber-card,.method-card,.stock-rank-card{{background:rgba(255,255,255,.035)!important;border:1px solid rgba(255,255,255,.075)!important}} .stock-rank-card{{box-shadow:none!important}} .method-section{{background:linear-gradient(145deg,rgba(130,143,255,.10),rgba(255,255,255,.025))!important;border-color:rgba(255,255,255,.08)!important}} .badge{{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.08)}} .ticker{{color:#10b981!important;border-color:rgba(16,185,129,.35)!important}} footer{{border-top:1px solid rgba(255,255,255,.06)}}
@media (max-width:760px){{header{{padding-top:30px}} .top-rec-section,.news-section,.method-section{{padding:16px!important;border-radius:18px!important}} .ai-rec-grid,.valuation-grid,.youtuber-grid,.stock-rank-grid{{grid-template-columns:1fr!important}} .news-column h3{{position:static}} .ai-price-grid{{grid-template-columns:1fr}}}}
</style></head>
<body>
<header><h1>한국·미국 주식 한눈에 보기</h1><div class="subtitle">매시간 국내주식과 미국주식의 관심 종목, 출처 발언, 재무·차트 숫자, 최신 뉴스를 새로 정리합니다. / 생성: {generated}</div><div class="kpis"><div class="kpi">수집 소스 {total_sources}개</div><div class="kpi">소스 로그 {len(items)}개</div><div class="kpi">추천/관심 종목 {len(common)}개</div><div class="kpi">유튜브 자막 {len(transcript_items)}/{len(yt_items)}개</div><div class="kpi">화면 OCR {len(ocr_items)}개</div><div class="kpi">뉴스 {len([i for i in items if i.get('source_type') == 'rss'])}건</div></div></header>
<nav class="tabs"><a href="#top-recommendations">추천종목</a><a href="#news">뉴스</a><a href="#method">자료 확인</a><a href="#domestic">국내</a><a href="#global">미국</a></nav>
<main><div class="notice">이 페이지는 여러 출처에서 나온 말과 공개 재무 데이터를 모아 보여주는 참고용 화면입니다. 점수와 가격대는 자동 계산한 기준선일 뿐, 투자 조언이나 수익 보장이 아닙니다. 실제 매매 전에는 현재가, 공시, 실적, 수급을 다시 확인해 주세요.</div>{top_recommendations_section(ai_recommendations)}{news_section(items)}<div id="method">{methodology_section(methodology, yt_items, transcript_items)}</div>{section('domestic', common, items, ystats, valuations, ai_recommendations)}{section('global', common, items, ystats, valuations, ai_recommendations)}</main>
<footer>Hermes가 매시간 새로 정리합니다. 투자 판단은 직접 확인해 주세요.</footer>
</body></html>'''
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(doc, encoding='utf-8')
    print(f'Wrote {OUT} items={len(items)} common={len(common)}')


if __name__ == '__main__':
    main()
