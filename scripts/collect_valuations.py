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
    return {
        'ticker': ticker, 'name': name, 'region': region,
        'price': price, 'currency': metrics.get('currency') or ('USD' if region == 'global' else 'KRW'),
        'pe': metrics.get('pe'), 'forward_pe': metrics.get('forward_pe'), 'pb': pb, 'roe': roe,
        'profit_margin': metrics.get('profit_margin'), 'eps': eps,
        'fair_value': fair, 'watch_buy_price': buy, 'margin_to_fair_pct': margin_to_fair,
        'verdict': verdict, 'action': action, 'rationale': rationale,
        'score': score, 'positives': positives[:4], 'risks': risks[:4],
        'valuation_basis': valuation_basis[:3], 'data_sources': metrics.get('sources', []),
        'fetch_note': metrics.get('fetch_note', ''),
    }


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
            valuations.append(judge(c['region'], c['ticker'], c['name'], c['mention_count'], metrics))
        except Exception as e:
            valuations.append({'region': c['region'], 'ticker': c['ticker'], 'name': c['name'], 'verdict': '자료 부족', 'action': '수집 실패', 'rationale': str(e)[:200]})
    out = {'generated_at': datetime.now().isoformat(timespec='minutes'), 'method': '공개 재무지표(PER/PBR/ROE/EPS/마진) 기반 휴리스틱 적정가·관찰매수가 산정. 투자 조언이 아니라 검토용 스크리닝입니다.', 'valuations': valuations}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'wrote {OUT} valuations={len(valuations)}')
    for v in valuations[:12]:
        print(v.get('region'), v.get('ticker'), v.get('verdict'), 'price=', fmt_num(v.get('price')), 'fair=', fmt_num(v.get('fair_value')), 'buy=', fmt_num(v.get('watch_buy_price')))


if __name__ == '__main__':
    main()
