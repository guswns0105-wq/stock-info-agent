#!/usr/bin/env python3
"""Collect lightweight financial metrics and heuristic valuation notes for mentioned stocks.

The output is intentionally framed as an information/valuation screen, not a buy/sell order.
It uses public pages without API keys:
- Yahoo chart endpoint for latest price where available
- StockAnalysis statistics pages for US/global tickers
- Naver Finance item pages for Korean tickers
"""
import json
import math
import re
import urllib.request
from datetime import datetime
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / 'data' / 'common_recommendations.json'
LEX = ROOT / 'config' / 'stocks_lexicon.json'
OUT = ROOT / 'data' / 'valuations.json'
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X) Hermes Stock Agent/1.0'


def fetch_text(url, timeout=20, encoding='utf-8'):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'ko,en;q=0.8'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(1_500_000)
        if encoding == 'auto':
            ctype = r.headers.get('content-type', '')
            m = re.search(r'charset=([^;]+)', ctype, re.I)
            encoding = m.group(1) if m else 'utf-8'
        return raw.decode(encoding, 'ignore')


def to_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    s = unescape(str(value)).strip().replace(',', '').replace('%', '')
    s = re.sub(r'[^0-9.\-]', '', s)
    if not s or s in {'-', '.', '-.'}:
        return None
    try:
        return float(s)
    except Exception:
        return None


def fmt_num(value, suffix=''):
    if value is None:
        return '확인 불가'
    if abs(value) >= 1000:
        return f'{value:,.0f}{suffix}'
    if abs(value) >= 100:
        return f'{value:,.1f}{suffix}'
    return f'{value:,.2f}{suffix}'


def yahoo_price(symbol):
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d'
    try:
        data = json.loads(fetch_text(url))
        result = (data.get('chart', {}).get('result') or [])[0]
        meta = result.get('meta', {})
        price = meta.get('regularMarketPrice') or meta.get('previousClose')
        currency = meta.get('currency') or ''
        return to_float(price), currency
    except Exception:
        return None, ''


def yahoo_chart(symbol, rng='1y'):
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={rng}&interval=1d'
    try:
        data = json.loads(fetch_text(url))
        result = (data.get('chart', {}).get('result') or [])[0]
        quote = (result.get('indicators', {}).get('quote') or [{}])[0]
        closes = [to_float(x) for x in quote.get('close', [])]
        closes = [x for x in closes if x is not None and x > 0]
        return closes
    except Exception:
        return []


def chart_symbol(region, ticker):
    if region == 'global':
        return ticker.upper()
    # Try Korea main board first; if no chart data, fallback to KQ.
    for suffix in ['.KS', '.KQ']:
        sym = f'{ticker}{suffix}'
        if yahoo_chart(sym, '1mo'):
            return sym
    return f'{ticker}.KS'


def avg(xs):
    return sum(xs) / len(xs) if xs else None


def collect_chart(region, ticker, current_price=None):
    sym = chart_symbol(region, ticker)
    closes = yahoo_chart(sym, '1y')
    if not closes:
        return {'chart_symbol': sym, 'chart_status': '차트 데이터 부족'}
    last = current_price or closes[-1]
    high_52w = max(closes)
    low_52w = min(closes)
    sma20 = avg(closes[-20:])
    sma60 = avg(closes[-60:])
    sma120 = avg(closes[-120:])
    ret20 = ((last / closes[-21]) - 1) * 100 if len(closes) > 21 and closes[-21] else None
    ret60 = ((last / closes[-61]) - 1) * 100 if len(closes) > 61 and closes[-61] else None
    recent_support = min(closes[-60:]) if len(closes) >= 20 else low_52w
    recent_resistance = max(closes[-60:]) if len(closes) >= 20 else high_52w
    vol = None
    if len(closes) > 25:
        rets = [(closes[i] / closes[i-1] - 1) for i in range(1, len(closes)) if closes[i-1]]
        m = avg(rets[-60:]) or 0
        vol = (sum((x-m)**2 for x in rets[-60:]) / max(1, len(rets[-60:])-1)) ** 0.5 * (252 ** 0.5) * 100
    trend = '상승 추세' if (sma20 and sma60 and last > sma20 > sma60) else ('하락/약세 추세' if (sma20 and sma60 and last < sma20 < sma60) else '중립 추세')
    technical_score = 0
    if trend == '상승 추세': technical_score += 2
    elif trend == '중립 추세': technical_score += 1
    else: technical_score -= 1
    if ret20 is not None:
        if 0 <= ret20 <= 15: technical_score += 1
        elif ret20 > 35: technical_score -= 2
        elif ret20 < -15: technical_score -= 1
    if low_52w and high_52w and high_52w > low_52w:
        pos = (last - low_52w) / (high_52w - low_52w)
        if 0.25 <= pos <= 0.75: technical_score += 1
        elif pos > 0.92: technical_score -= 1
    else:
        pos = None
    return {
        'chart_symbol': sym,
        'chart_status': 'ok',
        'sma20': sma20, 'sma60': sma60, 'sma120': sma120,
        'ret20_pct': ret20, 'ret60_pct': ret60,
        'high_52w': high_52w, 'low_52w': low_52w,
        'recent_support': recent_support, 'recent_resistance': recent_resistance,
        'volatility_pct': vol, 'trend': trend, 'technical_score': technical_score,
        'position_52w': pos,
    }


def stockanalysis_stat(html, label):
    # Table row pattern used by stockanalysis.com statistics pages.
    m = re.search(re.escape(label) + r'.{0,450}?<td[^>]*title="([^"]+)"', html, re.S)
    if not m:
        m = re.search(re.escape(label) + r'.{0,450}?<td[^>]*>(.*?)</td>', html, re.S)
    if not m:
        return None
    return to_float(re.sub('<[^>]+>', '', m.group(1)))


def collect_global(ticker):
    sym = ticker.upper()
    price, currency = yahoo_price(sym)
    metrics = {'price': price, 'currency': currency or 'USD'}
    sources = [f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}']
    try:
        html = fetch_text(f'https://stockanalysis.com/stocks/{sym.lower()}/statistics/')
        sources.append(f'https://stockanalysis.com/stocks/{sym.lower()}/statistics/')
        metrics.update({
            'pe': stockanalysis_stat(html, 'PE Ratio'),
            'forward_pe': stockanalysis_stat(html, 'Forward PE'),
            'ps': stockanalysis_stat(html, 'PS Ratio'),
            'pb': stockanalysis_stat(html, 'PB Ratio') or stockanalysis_stat(html, 'Price / Book'),
            'roe': stockanalysis_stat(html, 'Return on Equity'),
            'profit_margin': stockanalysis_stat(html, 'Profit Margin'),
            'debt_to_equity': stockanalysis_stat(html, 'Debt / Equity Ratio'),
            'revenue': stockanalysis_stat(html, 'Revenue'),
            'net_income': stockanalysis_stat(html, 'Net Income'),
        })
    except Exception as e:
        metrics['fetch_note'] = f'StockAnalysis 통계 수집 실패: {str(e)[:120]}'
    metrics['sources'] = sources
    return metrics


def naver_first_number_after(html, label):
    i = html.find(label)
    if i < 0:
        return None
    frag = html[i:i+1600]
    nums = re.findall(r'<td[^>]*>\s*([^<]*?[-+]?\d[\d,]*(?:\.\d+)?)\s*(?:</td>|\n)', frag, re.S)
    for n in nums:
        v = to_float(n)
        if v is not None:
            return v
    return None


def naver_current_price(html):
    m = re.search(r'<p class="no_today">.*?<span class="blind">([0-9,]+)</span>', html, re.S)
    return to_float(m.group(1)) if m else None


def collect_domestic(ticker):
    metrics = {'currency': 'KRW'}
    sources = [f'https://finance.naver.com/item/main.naver?code={ticker}']
    price, cur = yahoo_price(f'{ticker}.KS')
    if price is None:
        price, cur = yahoo_price(f'{ticker}.KQ')
    try:
        html = fetch_text(sources[0], encoding='euc-kr')
        # For Korean tickers prefer Naver's on-page price; Yahoo chart can return
        # adjusted or stale values that differ materially for some KR tickers.
        naver_price = naver_current_price(html)
        metrics.update({
            'price': naver_price or price,
            'pe': naver_first_number_after(html, 'PER'),
            'pb': naver_first_number_after(html, 'PBR'),
            'roe': naver_first_number_after(html, 'ROE'),
            'eps': naver_first_number_after(html, 'EPS'),
        })
    except Exception as e:
        metrics.update({'price': price, 'fetch_note': f'Naver Finance 수집 실패: {str(e)[:120]}'})
    metrics['sources'] = sources + ([f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}.KS'] if price else [])
    return metrics


def target_multiples(region, metrics):
    roe = metrics.get('roe')
    margin = metrics.get('profit_margin')
    if region == 'global':
        target_pe = 22
        if roe and roe >= 30: target_pe += 8
        if margin and margin >= 25: target_pe += 6
        if metrics.get('forward_pe') and metrics['forward_pe'] < 20: target_pe += 2
        target_pe = min(target_pe, 40)
        target_pb = 4.0 if (roe and roe >= 20) else 2.5
    else:
        target_pe = 12
        if roe and roe >= 15: target_pe += 5
        elif roe and roe >= 8: target_pe += 2
        target_pe = min(target_pe, 22)
        target_pb = 1.2 if not roe else min(2.5, max(0.8, roe / 8))
    return target_pe, target_pb


def judge(region, ticker, name, mention_count, metrics):
    price = metrics.get('price')
    pe = metrics.get('forward_pe') or metrics.get('pe')
    pb = metrics.get('pb')
    eps = metrics.get('eps')
    roe = metrics.get('roe')
    target_pe, target_pb = target_multiples(region, metrics)
    fair_values = []
    valuation_basis = []
    if price and pe and pe > 0:
        implied_eps = price / pe
        fair_values.append(implied_eps * target_pe)
        valuation_basis.append(f'PER {fmt_num(pe)}배 → 기준 PER {fmt_num(target_pe)}배')
    if eps and eps > 0:
        fair_values.append(eps * target_pe)
        valuation_basis.append(f'EPS {fmt_num(eps)} → 기준 PER {fmt_num(target_pe)}배')
    if price and pb and pb > 0:
        book = price / pb
        fair_values.append(book * target_pb)
        valuation_basis.append(f'PBR {fmt_num(pb)}배 → 기준 PBR {fmt_num(target_pb)}배')
    fair = sum(fair_values) / len(fair_values) if fair_values else None
    buy = fair * 0.82 if fair else None
    margin_to_fair = ((fair / price) - 1) * 100 if fair and price else None
    score = 0
    positives = []
    risks = []
    if mention_count >= 3:
        score += 1; positives.append(f'출처 언급 {mention_count}회')
    if roe is not None:
        if roe >= 15: score += 2; positives.append(f'ROE {fmt_num(roe, "%")}')
        elif roe >= 8: score += 1; positives.append(f'ROE {fmt_num(roe, "%")}')
        elif roe < 5: score -= 1; risks.append(f'ROE 낮음 {fmt_num(roe, "%")}')
    if pe is not None:
        if pe <= target_pe * 0.8: score += 2; positives.append(f'PER가 기준보다 낮음')
        elif pe <= target_pe: score += 1
        elif pe > target_pe * 1.6: score -= 2; risks.append(f'PER 부담 {fmt_num(pe)}배')
    if pb is not None and region == 'domestic':
        if pb <= 1.0: score += 1; positives.append(f'PBR {fmt_num(pb)}배')
        elif pb > 3: score -= 1; risks.append(f'PBR 부담 {fmt_num(pb)}배')
    if margin_to_fair is not None:
        if margin_to_fair >= 25: score += 2
        elif margin_to_fair >= 8: score += 1
        elif margin_to_fair < -15: score -= 2
    if fair is None:
        verdict = '자료 부족'
        action = '재무 데이터 확인 후 판단'
        rationale = '공개 페이지에서 가격·PER/PBR/EPS 중 충분한 조합을 확보하지 못했습니다.'
    elif price <= buy:
        verdict = '저평가 후보'
        action = f'{fmt_num(buy)} {metrics.get("currency", "")} 이하부터 분할 관심'
        rationale = '현재가가 보수적 관찰매수가 이하입니다.'
    elif price <= fair:
        verdict = '관심권'
        action = f'{fmt_num(buy)} {metrics.get("currency", "")} 부근까지 조정 시 매력 증가'
        rationale = '적정가 아래이지만 안전마진은 크지 않습니다.'
    elif price <= fair * 1.15:
        verdict = '중립/대기'
        action = f'{fmt_num(buy)} {metrics.get("currency", "")} 근처 대기'
        rationale = '적정가와 현재가 차이가 작아 추격보다 조정 대기가 낫습니다.'
    else:
        verdict = '고평가 주의'
        action = f'{fmt_num(buy)} {metrics.get("currency", "")} 이하가 아니면 보수적 접근'
        rationale = '현재가가 보수 산정 적정가를 의미 있게 웃돕니다.'
    chart = metrics.get('chart', {}) or {}
    technical_score = chart.get('technical_score') or 0
    ai_score = score + technical_score + min(3, mention_count / 4)
    if margin_to_fair is not None and margin_to_fair < -25:
        ai_score -= 2
    if pe is not None and pe > target_pe * 2.2:
        ai_score -= 1
    fair_sell = fair * 1.05 if fair else None
    resistance_sell = chart.get('recent_resistance')
    if fair_sell and resistance_sell:
        target_sell = min(max(price or 0, fair_sell), max(fair_sell, resistance_sell))
    else:
        target_sell = fair_sell or resistance_sell
    support = chart.get('recent_support')
    if buy and support and price:
        target_buy = max(min(price * 0.98, support * 1.03), min(buy, price * 0.98))
    else:
        target_buy = buy
    comment_bits=[]
    if mention_count:
        comment_bits.append(f'출처 언급 {mention_count}회')
    if margin_to_fair is not None:
        comment_bits.append(f'적정가 대비 {fmt_num(margin_to_fair, "%")} 여력')
    if chart.get('trend'):
        comment_bits.append(chart.get('trend'))
    if roe:
        comment_bits.append(f'ROE {fmt_num(roe, "%")}')
    ai_comment = ', '.join(comment_bits[:4]) + ' 기준으로 산정했습니다.' if comment_bits else rationale
    return {
        'ticker': ticker, 'name': name, 'region': region, 'mention_count': mention_count,
        'price': price, 'currency': metrics.get('currency') or ('USD' if region == 'global' else 'KRW'),
        'pe': metrics.get('pe'), 'forward_pe': metrics.get('forward_pe'), 'pb': pb, 'roe': roe,
        'profit_margin': metrics.get('profit_margin'), 'eps': eps,
        'fair_value': fair, 'watch_buy_price': buy, 'ai_buy_price': target_buy, 'ai_sell_price': target_sell, 'margin_to_fair_pct': margin_to_fair,
        'verdict': verdict, 'action': action, 'rationale': rationale,
        'score': score, 'technical_score': technical_score, 'ai_score': ai_score, 'ai_comment': ai_comment,
        'positives': positives[:4], 'risks': risks[:4],
        'valuation_basis': valuation_basis[:3], 'chart': chart, 'data_sources': metrics.get('sources', []),
        'fetch_note': metrics.get('fetch_note', ''),
    }


def build_recommendation(rank, v):
    return {
        'rank': rank, 'ticker': v.get('ticker'), 'name': v.get('name'), 'region': v.get('region'),
        'price': v.get('price'), 'currency': v.get('currency'),
        'ai_score': v.get('ai_score'), 'verdict': v.get('verdict'),
        'ai_buy_price': v.get('ai_buy_price'), 'ai_sell_price': v.get('ai_sell_price'), 'fair_value': v.get('fair_value'),
        'pe': v.get('forward_pe') or v.get('pe'), 'pb': v.get('pb'), 'roe': v.get('roe'),
        'trend': (v.get('chart') or {}).get('trend'), 'ret20_pct': (v.get('chart') or {}).get('ret20_pct'),
        'support': (v.get('chart') or {}).get('recent_support'), 'resistance': (v.get('chart') or {}).get('recent_resistance'),
        'comment': v.get('ai_comment'),
        'why': [*(v.get('positives') or [])[:3], f"차트: {(v.get('chart') or {}).get('trend','확인 불가')}"],
        'risk_comment': '과열 추격 금지, 적정매수가 이탈 시만 분할 접근. 실적·공시 확인 필요.'
    }


def make_ai_recommendations(valuations):
    eligible = [v for v in valuations if v.get('price') and v.get('fair_value') and v.get('ai_buy_price') and v.get('ai_sell_price')]
    # 고평가 주의는 Top3에서 제외하고, 가치+차트+언급량을 종합해 시장별로 정렬한다.
    eligible = [v for v in eligible if v.get('verdict') != '고평가 주의']
    def sort_key(v):
        return (v.get('ai_score', -99), v.get('margin_to_fair_pct') or -999, v.get('mention_count') or 0)
    grouped = {'domestic': [], 'global': []}
    for region in grouped:
        region_items = [v for v in eligible if v.get('region') == region]
        region_items.sort(key=sort_key, reverse=True)
        grouped[region] = [build_recommendation(rank, v) for rank, v in enumerate(region_items[:3], 1)]
    # Backward-compatible flat list: 국내 3개 다음 미국/해외 3개.
    flat = grouped['domestic'] + grouped['global']
    return {'domestic': grouped['domestic'], 'global': grouped['global'], 'flat': flat}


def main():
    common = json.loads(COMMON.read_text(encoding='utf-8')) if COMMON.exists() else []
    lex = json.loads(LEX.read_text(encoding='utf-8'))
    # 조사 범위: 대시보드에 실제 언급된 종목 전체. 너무 많아질 때는 상위 40개로 제한.
    candidates = []
    seen = set()
    for rec in common:
        key = (rec.get('region'), rec.get('ticker'))
        if key in seen:
            continue
        seen.add(key)
        candidates.append({
            'region': rec.get('region'),
            'ticker': rec.get('ticker'),
            'name': rec.get('name') or lex.get(rec.get('region',''), {}).get(rec.get('ticker'), rec.get('ticker')),
            'mention_count': len(rec.get('evidence', [])) or rec.get('source_count', 0),
        })
    candidates.sort(key=lambda x: x['mention_count'], reverse=True)
    limit = int(__import__('os').environ.get('STOCK_VALUATION_LIMIT', '40'))
    valuations = []
    for c in candidates[:limit]:
        try:
            metrics = collect_global(c['ticker']) if c['region'] == 'global' else collect_domestic(c['ticker'])
            metrics['chart'] = collect_chart(c['region'], c['ticker'], metrics.get('price'))
            valuations.append(judge(c['region'], c['ticker'], c['name'], c['mention_count'], metrics))
        except Exception as e:
            valuations.append({'region': c['region'], 'ticker': c['ticker'], 'name': c['name'], 'verdict': '자료 부족', 'action': '수집 실패', 'rationale': str(e)[:200]})
    ai_recommendations = make_ai_recommendations(valuations)
    out = {'generated_at': datetime.now().isoformat(timespec='minutes'), 'method': '공개 재무지표(PER/PBR/ROE/EPS/마진) + Yahoo 1년 일봉 차트(SMA/52주 범위/20·60일 모멘텀) 기반 국내 AI 추천 Top3와 미국/해외 AI 추천 Top3 분리 산정. 투자 조언이 아니라 검토용 스크리닝입니다.', 'ai_recommendations': ai_recommendations, 'valuations': valuations}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'wrote {OUT} valuations={len(valuations)} ai_top3_domestic={len(ai_recommendations.get("domestic", []))} ai_top3_global={len(ai_recommendations.get("global", []))}')
    for region in ['domestic', 'global']:
        for r in ai_recommendations.get(region, []):
            print('AI_TOP', region, r['rank'], r['ticker'], r['name'], 'buy=', fmt_num(r.get('ai_buy_price')), 'sell=', fmt_num(r.get('ai_sell_price')), 'score=', fmt_num(r.get('ai_score')))
    for v in valuations[:12]:
        print(v.get('region'), v.get('ticker'), v.get('verdict'), 'price=', fmt_num(v.get('price')), 'fair=', fmt_num(v.get('fair_value')), 'buy=', fmt_num(v.get('watch_buy_price')))


if __name__ == '__main__':
    main()
