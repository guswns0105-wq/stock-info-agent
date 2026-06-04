#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DEPS=ROOT/'.python-deps'
if DEPS.exists():
    sys.path.insert(0, str(DEPS))

import json, re, html, urllib.request, urllib.parse, xml.etree.ElementTree as ET
import os, shutil, subprocess, tempfile, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from html.parser import HTMLParser

DATA=ROOT/'data'/'items.json'; RAW=ROOT/'data'/'raw_sources.json'; COMMON=ROOT/'data'/'common_recommendations.json'; YSTATS=ROOT/'data'/'youtuber_stats.json'
NEWS_MD=ROOT/'data'/'news_ingest'/'latest_news.md'; NEWS_HISTORY=ROOT/'data'/'news_ingest'/'news_history.jsonl'; NEWS_TRANSLATION_CACHE=ROOT/'data'/'news_ingest'/'translation_cache.json'
HISTORY=ROOT/'data'/'items_history.jsonl'
TRANSCRIPTS=ROOT/'data'/'transcripts'
SOURCES=ROOT/'config'/'sources.json'; LEX=ROOT/'config'/'stocks_lexicon.json'
RATE_LIMIT_FILE=TRANSCRIPTS/'youtube_caption_rate_limited_until.txt'
OCR_INDEX=ROOT/'data'/'youtube_ocr'/'ocr_index.json'
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X) Hermes Stock Agent/1.0'
YOUTUBE_LATEST_LIMIT=int(os.environ.get('STOCK_YOUTUBE_LATEST_LIMIT','10'))
STOCK_ALIASES={
    'global': {
        'PLTR': ['팔란티어', 'palantir'],
        'MU': ['마이크론', 'micron'],
        'IONQ': ['아이온큐', 'ionq'],
        'NVDA': ['엔비디아', 'nvidia'],
        'TSLA': ['테슬라', 'tesla'],
        'TSM': ['tsmc', '대만반도체'],
        'ASML': ['asml'],
        'AMD': ['amd'],
        'SOXX': ['soxx', '반도체 etf'],
        'QQQ': ['qqq', '나스닥100'],
    },
    'domestic': {}
}
PRECISE_YOUTUBE=os.environ.get('STOCK_PRECISE_YOUTUBE','1') != '0'
TRANSCRIPT_WORKERS=int(os.environ.get('STOCK_TRANSCRIPT_WORKERS','1'))
YOUTUBE_REQUIRE_TRANSCRIPT=os.environ.get('STOCK_YOUTUBE_REQUIRE_TRANSCRIPT','1') != '0'

class TextExtractor(HTMLParser):
    def __init__(self): super().__init__(); self.skip=False; self.parts=[]
    def handle_starttag(self, tag, attrs):
        if tag in ('script','style','noscript'): self.skip=True
    def handle_endtag(self, tag):
        if tag in ('script','style','noscript'): self.skip=False
    def handle_data(self, data):
        if not self.skip:
            t=' '.join(data.split())
            if t: self.parts.append(t)

def fetch(url, timeout=20):
    req=urllib.request.Request(url, headers={'User-Agent':UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data=r.read(2_000_000)
        ctype=r.headers.get('content-type','')
        return r.geturl(), ctype, data

def visible_text(b):
    p=TextExtractor(); p.feed(b.decode('utf-8','ignore')); return ' '.join(p.parts)

def yt_oembed(video_id):
    url='https://www.youtube.com/oembed?format=json&url='+urllib.parse.quote('https://www.youtube.com/watch?v='+video_id)
    try:
        _,_,b=fetch(url); return json.loads(b.decode()).get('title','')
    except Exception: return ''

def strip_vtt(vtt_text):
    lines=[]
    for line in vtt_text.splitlines():
        line=line.strip()
        if not line or line == 'WEBVTT' or line.startswith('Kind:') or line.startswith('Language:'): continue
        if '-->' in line or re.fullmatch(r'\d+', line): continue
        line=re.sub(r'<[^>]+>', ' ', line)
        line=html.unescape(line)
        line=' '.join(line.split())
        if line and (not lines or lines[-1] != line): lines.append(line)
    return ' '.join(lines)

def get_local_asr_transcript(video_id, pack_path=''):
    """Read user-approved local-pack ASR transcripts (e.g. 경제사냥꾼 50 Shorts)."""
    if not pack_path:
        return '', 'no local ASR pack configured'
    pack=Path(pack_path)
    if not pack.exists():
        return '', 'local ASR pack missing'
    candidates=[pack/'asr'/f'{video_id}.transcript.txt']
    item_file=pack/'asr_items.json'
    if item_file.exists():
        try:
            for item in json.loads(item_file.read_text(encoding='utf-8')):
                if item.get('video_id') == video_id and item.get('transcript_path'):
                    candidates.insert(0, Path(item['transcript_path']))
        except Exception:
            pass
    for p in candidates:
        try:
            if p.exists() and p.stat().st_size > 20:
                text=p.read_text(encoding='utf-8', errors='ignore')
                # Cache into repo-local transcript cache so future 4h cron runs use it instantly.
                TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
                (TRANSCRIPTS/f'{video_id}.txt').write_text(text, encoding='utf-8')
                (TRANSCRIPTS/f'{video_id}.json').write_text(json.dumps({'video_id':video_id,'method':'local_pack_asr','status':'ok','pack_path':str(pack)}, ensure_ascii=False, indent=2), encoding='utf-8')
                return text, 'ok'
        except Exception:
            continue
    return '', 'local ASR transcript not found'

def get_youtube_transcript(video_id, local_asr_pack=''):
    TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
    cache=TRANSCRIPTS/f'{video_id}.txt'; meta=TRANSCRIPTS/f'{video_id}.json'
    if cache.exists() and cache.stat().st_size > 20:
        return cache.read_text(encoding='utf-8', errors='ignore'), 'cache', 'ok'
    local_text, local_status = get_local_asr_transcript(video_id, local_asr_pack)
    if local_text:
        return local_text, 'local_pack_asr', 'ok'
    if RATE_LIMIT_FILE.exists():
        try:
            until=float(RATE_LIMIT_FILE.read_text().strip() or '0')
            if until > time.time():
                return '', 'rate_limited', 'YouTube timedtext 자막 요청이 429로 제한되어 다음 실행에서 재시도합니다.'
        except Exception:
            pass
    url='https://www.youtube.com/watch?v='+video_id
    errors=[]
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        # Korean Shorts often expose captions as `ko-orig` (original Korean) plus translated tracks.
        # Prefer Korean/original captions before falling back to English.
        api=YouTubeTranscriptApi(); fetched=api.fetch(video_id, languages=['ko-orig','ko','en'])
        text=' '.join(snippet.text for snippet in fetched if getattr(snippet, 'text', '').strip())
        if len(text) > 20:
            cache.write_text(text, encoding='utf-8')
            meta.write_text(json.dumps({'video_id':video_id,'method':'youtube_transcript_api','status':'ok'}, ensure_ascii=False, indent=2), encoding='utf-8')
            return text, 'youtube_transcript_api', 'ok'
    except Exception as e:
        errors.append('youtube_transcript_api: '+str(e).split('\n')[0][:220])
    ytdlp=shutil.which('yt-dlp') or '/Users/mac1/.hermes-4/home/.local/bin/yt-dlp'
    if os.path.exists(ytdlp):
        with tempfile.TemporaryDirectory() as td:
            outtmpl=str(Path(td)/'%(id)s.%(ext)s')
            cmd=[ytdlp,'--skip-download','--write-auto-subs','--write-subs','--sub-langs','ko-orig,ko,en','--sub-format','vtt','--ignore-no-formats-error','--extractor-args','youtube:player_client=android;lang=ko','--sleep-subtitles','3','--retries','3','--socket-timeout','20','--no-warnings','-o',outtmpl,url]
            if os.environ.get('STOCK_YTDLP_COOKIES') == '1':
                cmd[1:1]=['--cookies-from-browser','chrome']
            try:
                env=os.environ.copy(); env['HOME']='/Users/mac1'
                proc=subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=int(os.environ.get('STOCK_TRANSCRIPT_TIMEOUT','60')), env=env)
                vtts=list(Path(td).glob(f'{video_id}*.vtt'))
                if vtts:
                    raw='\n'.join(v.read_text(encoding='utf-8', errors='ignore') for v in vtts)
                    text=strip_vtt(raw)
                    if len(text) > 20:
                        cache.write_text(text, encoding='utf-8')
                        meta.write_text(json.dumps({'video_id':video_id,'method':'yt-dlp','status':'ok','files':[v.name for v in vtts]}, ensure_ascii=False, indent=2), encoding='utf-8')
                        return text, 'yt-dlp', 'ok'
                errors.append('yt-dlp: '+(proc.stderr or proc.stdout)[-350:])
            except Exception as e:
                errors.append('yt-dlp: '+str(e)[:220])
    status='; '.join(errors)[:700] or 'no transcript tool available'
    if '429' in status or 'Too Many Requests' in status:
        RATE_LIMIT_FILE.write_text(str(time.time()+60*60), encoding='utf-8')
    meta.write_text(json.dumps({'video_id':video_id,'method':'none','status':'failed','errors':errors}, ensure_ascii=False, indent=2), encoding='utf-8')
    return '', 'none', status

def clean_text(text):
    text=re.sub(r'자막추출 실패/없음:.*', '', text or '', flags=re.S)
    text=re.sub(r'\s+', ' ', text).strip()
    return text


def is_probably_english(text):
    letters=re.findall(r'[A-Za-z]', text or '')
    hangul=re.findall(r'[가-힣]', text or '')
    return len(letters) >= 12 and len(letters) > max(3, len(hangul) * 2)

def load_translation_cache():
    try:
        return json.loads(NEWS_TRANSLATION_CACHE.read_text(encoding='utf-8')) if NEWS_TRANSLATION_CACHE.exists() else {}
    except Exception:
        return {}

def save_translation_cache(cache):
    NEWS_TRANSLATION_CACHE.parent.mkdir(parents=True, exist_ok=True)
    NEWS_TRANSLATION_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')

def translate_en_to_ko(text, cache):
    text=clean_text(text or '')[:450]
    if not text or not is_probably_english(text):
        return text
    if text in cache:
        return cache[text]
    url='https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=ko&dt=t&q='+urllib.parse.quote(text)
    try:
        req=urllib.request.Request(url, headers={'User-Agent':UA})
        with urllib.request.urlopen(req, timeout=12) as r:
            data=json.loads(r.read().decode('utf-8','ignore'))
        translated=''.join(part[0] for part in (data[0] or []) if part and part[0]).strip()
        cache[text]=translated or text
    except Exception as e:
        cache[text]=text
    return cache[text]

def enrich_news_translations(item, cache):
    if item.get('source_type') != 'rss' or item.get('region') != 'global':
        return item
    title=item.get('title') or ''
    summary=item.get('summary') or ''
    ko_title=translate_en_to_ko(title, cache)
    ko_summary=translate_en_to_ko(summary, cache) if summary and is_probably_english(summary) else summary
    item['title_original']=title
    item['summary_original']=summary
    item['title_ko']=ko_title
    item['summary_ko']=ko_summary
    item['title']=ko_title
    item['summary']=ko_summary
    item['translation_note']='자동번역: Google Translate public endpoint; 원문은 title_original/summary_original 및 링크 참조'
    return item

def write_news_markdown(items, now):
    NEWS_MD.parent.mkdir(parents=True, exist_ok=True)
    news=[x for x in items if x.get('source_type') == 'rss']
    lines=[f'# 주식 뉴스 인제스트 ({now})', '', '이 파일은 1시간 크론이 읽기 쉽게 최신 RSS/Google News 헤드라인을 한국어 중심 Markdown으로 정규화한 자료입니다.', '투자 조언이 아니라 뉴스/촉매/리스크 확인용 출처 목록입니다.', '']
    for region,label in [('domestic','한국시장 뉴스'),('global','미국시장 뉴스')]:
        rows=[x for x in news if x.get('region') == region][:30]
        lines += [f'## {label}', '']
        if not rows:
            lines += ['- 수집된 뉴스 없음', '']
            continue
        for idx,item in enumerate(rows,1):
            title=item.get('title') or '제목 없음'
            source=item.get('source') or '출처'
            pub=item.get('published_at') or item.get('collected_at') or ''
            url=item.get('url') or ''
            summary=clean_text(item.get('summary') or '')[:260]
            tickers=', '.join(item.get('tickers') or []) or '종목 미검출'
            lines.append(f'### {idx}. {title}')
            lines.append(f'- 시장: {label.replace(" 뉴스", "")}')
            lines.append(f'- 출처: {source}')
            if pub: lines.append(f'- 시각: {pub}')
            lines.append(f'- 관련 티커: {tickers}')
            if item.get('title_original') and item.get('title_original') != title:
                lines.append(f'- 원문 제목: {item.get("title_original")}')
            if summary:
                lines.append(f'- 요약: {summary}')
            if url:
                lines.append(f'- 링크: {url}')
            lines.append('')
    NEWS_MD.write_text('\n'.join(lines), encoding='utf-8')
    with NEWS_HISTORY.open('a', encoding='utf-8') as f:
        f.write(json.dumps({'generated_at':now,'news_count':len(news),'domestic':sum(1 for x in news if x.get('region')=='domestic'),'global':sum(1 for x in news if x.get('region')=='global'),'path':str(NEWS_MD)}, ensure_ascii=False)+'\n')
    print(f'wrote {NEWS_MD} news={len(news)}')

def split_sentences(text):
    text=clean_text(text)
    parts=re.split(r'(?<=[.!?。！？])\s+|\n+|(?<=[다요죠음함됨임])\s+(?=[가-힣A-Z0-9"\'“‘])', text)
    return [p.strip(' -·•') for p in parts if len(p.strip()) >= 8]

def infer_source_role(source_type):
    if source_type.startswith('youtube'): return '유튜버'
    if 'blog' in source_type: return '블로거'
    if source_type == 'rss': return '뉴스'
    return '소스'

def extract_price_fields(text, ticker=None, name=None):
    text=clean_text(text)
    money=r'(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?:\s*)(?:만원|원|달러|불|USD|KRW)'
    fields={'target_price':'출처에서 명시 안 됨','buy_zone':'출처에서 명시 안 됨','price_note':''}
    def is_relevant(ctx):
        if not ticker and not name:
            return True
        window=ctx.lower()
        return (ticker and ticker.lower() in window) or (name and name.lower() in window)
    for m in re.finditer(money, text):
        ctx=text[max(0,m.start()-80):m.end()+80]
        # 종목별 카드에서는 가격 주변에 해당 종목명이 함께 나올 때만 표시한다.
        # 없으면 다른 종목의 목표가를 끌어와 섞지 않는다.
        if not is_relevant(ctx):
            continue
        if fields['target_price'].startswith('출처') and re.search(r'목표가|적정가|타깃|target|목표', ctx, re.I):
            fields['target_price']=m.group(0); fields['price_note']=ctx.strip()
        if fields['buy_zone'].startswith('출처') and re.search(r'매수|진입|분할|눌림|지지|이하|아래|구간', ctx, re.I):
            fields['buy_zone']=m.group(0); fields['price_note']=ctx.strip()
    return fields

def infer_reason(text, title, ticker, name):
    hay=(title or '')+' '+clean_text(text)
    candidates=[]
    for s in split_sentences(hay)[:80]:
        if ticker in s or (name and name.lower() in s.lower()): candidates.append(s)
    if not candidates:
        for s in split_sentences(hay)[:20]:
            if re.search(r'추천|수혜|저평가|급등|대장주|목표가|호재|실적|AI|반도체|전망|방한|국민연금|인프라', s, re.I): candidates.append(s)
    if not candidates: candidates=[title or '근거 문장 추출 실패']
    # keep facts, no over-polish: preserve numbers/dates/names from source text
    return ' / '.join(candidates[:2])[:360]

def resolve_youtube_video_channel(src):
    vid=src.get('video_id') or src['url'].split('youtu.be/')[1].split('?')[0].split('/')[0]
    ytdlp=shutil.which('yt-dlp') or '/Users/mac1/.hermes-4/home/.local/bin/yt-dlp'
    if os.path.exists(ytdlp):
        try:
            proc=subprocess.run([ytdlp,'--skip-download','--dump-single-json','--ignore-no-formats-error','--no-warnings','https://youtu.be/'+vid], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
            if proc.returncode == 0 and proc.stdout.strip():
                data=json.loads(proc.stdout)
                cid=data.get('channel_id') or ''
                channel_url=data.get('channel_url') or data.get('uploader_url') or ''
                if cid or channel_url:
                    return {'name':data.get('channel') or data.get('uploader') or src.get('name','YouTube channel'), 'type':'youtube_channel', 'region':src.get('region','global'), 'url':channel_url or ('https://youtube.com/channel/'+cid), 'channel_id':cid, 'seed_video_id':vid}
        except Exception:
            pass
    return None

def youtube_channel_sources(srcs):
    channels=[]; seen=set()
    for bucket in ['domestic','global']:
        for src in srcs.get(bucket,[]):
            if src.get('type') == 'youtube_channel':
                ch=dict(src); ch['region']=src.get('region', bucket)
            elif src.get('type') == 'youtube_video':
                ch=resolve_youtube_video_channel(src)
            else:
                continue
            if not ch: continue
            key=ch.get('channel_id') or ch.get('url')
            if key in seen: continue
            seen.add(key); channels.append(ch)
    return channels

def collect_youtube_channel(src):
    cid=src.get('channel_id') or (src['url'].split('/channel/')[1].split('?')[0].split('/')[0] if '/channel/' in src.get('url','') else '')
    out=[]
    try:
        latest_limit=int(src.get('latest_limit') or YOUTUBE_LATEST_LIMIT)
        channel_title=src.get('name','')
        entries=[]
        seen_ids=set()

        def add_entry(entry, kind):
            vid=(entry.get('vid') or entry.get('id') or '').strip()
            if not vid or vid in seen_ids:
                return
            seen_ids.add(vid)
            entries.append({
                'vid':vid,
                'title':entry.get('title') or '',
                'published':entry.get('published') or '',
                'desc':entry.get('desc') or entry.get('description') or '',
                'kind':kind,
            })

        def collect_rss_videos():
            nonlocal channel_title
            if not cid:
                return
            feed=f'https://www.youtube.com/feeds/videos.xml?channel_id={cid}'
            _,_,b=fetch(feed)
            root=ET.fromstring(b)
            ns={'a':'http://www.w3.org/2005/Atom','yt':'http://www.youtube.com/xml/schemas/2015','m':'http://search.yahoo.com/mrss/'}
            channel_title=root.findtext('a:title', default=src.get('name',''), namespaces=ns) or src.get('name','')
            for e in root.findall('a:entry',ns)[:latest_limit]:
                desc=''; mg=e.find('m:group',ns)
                if mg is not None: desc=mg.findtext('m:description', default='', namespaces=ns)
                add_entry({
                    'vid':e.findtext('yt:videoId', default='', namespaces=ns),
                    'title':e.findtext('a:title', default='', namespaces=ns),
                    'published':e.findtext('a:published', default='', namespaces=ns),
                    'desc':desc,
                }, 'video')

        def collect_flat_tab(tab):
            nonlocal channel_title
            ytdlp=shutil.which('yt-dlp') or '/Users/mac1/.hermes-4/home/.local/bin/yt-dlp'
            base=src.get('url','').split('?')[0].rstrip('/')
            if cid:
                base='https://www.youtube.com/channel/'+cid
            tab_url=base+'/'+tab
            proc=subprocess.run([ytdlp,'--flat-playlist','--playlist-end',str(latest_limit),'--dump-single-json','--ignore-no-formats-error','--extractor-args','youtube:player_client=android;lang=ko','--no-warnings',tab_url], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
            if proc.returncode != 0 or not proc.stdout.strip():
                raise RuntimeError((proc.stderr or proc.stdout)[-400:])
            data=json.loads(proc.stdout)
            channel_title=(data.get('channel') or data.get('uploader') or data.get('title') or src.get('name','')).replace(' - Videos','').replace(' - Shorts','')
            kind='short' if tab == 'shorts' else 'video'
            for e in (data.get('entries') or [])[:latest_limit]:
                add_entry(e, kind)

        tabs=[]
        if src.get('prefer_shorts'):
            tabs=['shorts']
        else:
            tabs=['videos','shorts']
        for tab in tabs:
            try:
                if tab == 'videos' and cid:
                    collect_rss_videos()
                else:
                    collect_flat_tab(tab)
            except Exception as tab_error:
                # RSS can miss Shorts and some handle pages need yt-dlp; keep other tabs alive.
                if tab == 'videos' and not cid:
                    raise
                if tab == 'shorts':
                    print(f'warning: shorts collection failed for {src.get("name")}: {str(tab_error)[:180]}')

        transcripts={}
        def transcript_for(entry):
            vid=entry.get('vid')
            if not vid:
                return vid, '', 'none', 'no video id'
            cache=TRANSCRIPTS/f'{vid}.txt'
            if cache.exists() and cache.stat().st_size > 20:
                return vid, cache.read_text(encoding='utf-8', errors='ignore'), 'cache', 'ok'
            if PRECISE_YOUTUBE:
                text, method, status = get_youtube_transcript(vid, src.get('local_asr_pack',''))
                return vid, text, method, status
            return vid, '', 'metadata', 'metadata-only mode'
        workers=max(1, min(TRANSCRIPT_WORKERS, len(entries) or 1))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs=[ex.submit(transcript_for, entry) for entry in entries]
            for fut in as_completed(futs):
                vid, transcript, method, status=fut.result()
                transcripts[vid]=(transcript, method, status)
        for entry in entries:
            vid=entry['vid']; title=entry['title']; desc=entry['desc']; published=entry['published']
            transcript, method, status=transcripts.get(vid, ('', 'none', 'missing transcript task'))
            is_short = entry.get('kind') == 'short' or '#shorts' in (title+' '+desc).lower() or '/shorts/' in src.get('url','')
            summary = clean_text(transcript[:900] if transcript else '')
            if not summary: summary = '자막 추출 실패: 이 영상은 종목/근거 분석에서 제외했습니다.'
            confidence = 'transcript' if transcript else ('caption_failed' if YOUTUBE_REQUIRE_TRANSCRIPT else 'metadata')
            analysis_text = transcript if (transcript or YOUTUBE_REQUIRE_TRANSCRIPT) else (title+' '+desc)
            out.append({'source':channel_title,'channel_id':cid,'video_id':vid,'youtube_kind':'short' if is_short else 'video','source_type':'youtube_short' if is_short else 'youtube_video','region':src.get('region','domestic'),'title':title,'summary':summary,'url':'https://youtu.be/'+vid if vid else src['url'],'published_at':published,'text':analysis_text,'transcript_method':method,'transcript_status':'ok' if transcript else status,'transcript_chars':len(transcript),'extraction_quality':confidence})
    except Exception as e:
        out.append({'source':src.get('name','YouTube channel'),'channel_id':cid,'source_type':'youtube_channel','region':src.get('region','domestic'),'title':'수집 실패','summary':str(e),'url':src['url'],'published_at':'','text':'','transcript_method':'none','transcript_status':'channel feed failed','transcript_chars':0,'extraction_quality':'failed'})
    return out

def collect_youtube_video(src):
    vid=src.get('video_id') or src['url'].split('youtu.be/')[1].split('?')[0].split('/')[0]
    title=yt_oembed(vid) or src['name']
    transcript, method, status = get_youtube_transcript(vid)
    is_short = '/shorts/' in src.get('url','')
    summary = clean_text(transcript[:900]) if transcript else '자막 추출 실패: 이 영상은 종목/근거 분석에서 제외했습니다.'
    analysis_text = transcript if (transcript or YOUTUBE_REQUIRE_TRANSCRIPT) else title
    return [{'source':src['name'],'channel_id':src.get('channel_id',''),'video_id':vid,'source_type':'youtube_short' if is_short else 'youtube_video','region':src.get('region','global'),'title':title,'summary':summary,'url':'https://youtu.be/'+vid,'published_at':'','text':analysis_text,'transcript_method':method,'transcript_status':'ok' if transcript else status,'transcript_chars':len(transcript),'extraction_quality':'transcript' if transcript else ('caption_failed' if YOUTUBE_REQUIRE_TRANSCRIPT else 'metadata')}]

def collect_naver(src):
    try:
        final,ctype,b=fetch(src['url'])
        raw=b.decode('utf-8','ignore')
        text=visible_text(b)
        m=re.search(r'logNo\s*=\s*["\']?(\d+)', raw) or re.search(r'/PostView\.naver\?[^"\']*logNo=(\d+)', raw)
        if m:
            parsed=urllib.parse.urlparse(src['url']); blog=parsed.path.strip('/').split('/')[0]
            pv=f'https://blog.naver.com/PostView.naver?blogId={blog}&logNo={m.group(1)}&redirect=Dlog&widgetTypeCall=true&directAccess=false'
            try:
                final2,_,b2=fetch(pv); t2=visible_text(b2)
                if len(t2)>len(text): final,text=final2,t2
            except Exception: pass
        title=text[:80]
        return [{'source':src['name'].replace('Naver blog ','블로그 '),'source_type':'naver_blog_post','region':src.get('region','domestic'),'title':title or src['name'],'summary':clean_text(text[:700]),'url':src['url'],'published_at':'','text':text}]
    except Exception as e:
        return [{'source':src['name'],'source_type':'naver_blog_post','region':src.get('region','domestic'),'title':'수집 실패','summary':str(e),'url':src['url'],'published_at':'','text':''}]

def collect_rss(src):
    out=[]
    try:
        _,_,b=fetch(src['url']); root=ET.fromstring(b)
        for it in root.findall('.//item')[:5]:
            title=it.findtext('title') or ''; desc=it.findtext('description') or ''; link=it.findtext('link') or src['url']; pub=it.findtext('pubDate') or ''
            text=title+' '+re.sub('<[^>]+>',' ',desc)
            out.append({'source':src['name'],'source_type':'rss','region':src.get('region','domestic'),'title':title,'summary':clean_text(re.sub('<[^>]+>',' ',desc)[:500]),'url':link,'published_at':pub,'text':text})
    except Exception as e:
        out.append({'source':src['name'],'source_type':'rss','region':src.get('region','domestic'),'title':'수집 실패','summary':str(e),'url':src['url'],'published_at':'','text':''})
    return out

def detect_mentions(text, lex_region, market_region='domestic'):
    mentions=[]; low=text.lower()
    for code,name in lex_region.items():
        hit=False
        if re.search(r'(?<![A-Z0-9])'+re.escape(code)+r'(?![A-Z0-9])', text): hit=True
        if name and name.lower() in low: hit=True
        for alias in STOCK_ALIASES.get(market_region, {}).get(code, []):
            if alias.lower() in low:
                hit=True
        if code == '035420' and '네이버' not in text and not re.search(r'(?<![A-Z0-9])035420(?![A-Z0-9])', text): hit = False
        if hit: mentions.append({'ticker':code,'name':name,'market':market_region})
    return mentions

def detect_all_mentions(text, lex):
    mentions=[]; seen=set()
    for market in ['domestic','global']:
        for m in detect_mentions(text, lex.get(market, {}), market):
            key=(m['market'], m['ticker'])
            if key not in seen:
                seen.add(key); mentions.append(m)
    return mentions

def load_ocr_index():
    if not OCR_INDEX.exists():
        return {}
    try:
        raw=json.loads(OCR_INDEX.read_text(encoding='utf-8'))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}

def ocr_text_for(video_id, ocr_index):
    if not video_id:
        return '', None
    rec=ocr_index.get(video_id) or {}
    if rec.get('ocr_status') not in ('ok','no_text'):
        return '', rec
    path=rec.get('ocr_text_path')
    if path and Path(path).exists():
        try:
            return Path(path).read_text(encoding='utf-8', errors='ignore'), rec
        except Exception:
            pass
    return '', rec

def item_key(item):
    if item.get('video_id'):
        return 'youtube:'+str(item.get('video_id'))
    if item.get('url'):
        return 'url:'+str(item.get('url'))
    return 'source-title:'+str(item.get('source'))+'|'+str(item.get('title'))

def quality_rank(item):
    if item.get('confidence') == 'transcript':
        return 3
    if item.get('confidence') == 'source-title/meta':
        return 2
    if item.get('confidence') == 'metadata':
        return 1
    return 0

def merge_accumulated_items(current_items, now):
    """Keep historical source items so recommendations do not disappear on no-upload days."""
    previous=[]
    if DATA.exists():
        try:
            previous=json.loads(DATA.read_text(encoding='utf-8'))
        except Exception:
            previous=[]
    merged={}
    for item in previous:
        key=item_key(item)
        item.setdefault('first_seen_at', item.get('collected_at') or now)
        item.setdefault('last_seen_at', item.get('last_seen_at') or item.get('collected_at') or now)
        item.setdefault('accumulated', True)
        merged[key]=item
    newly=[]
    for item in current_items:
        key=item_key(item)
        old=merged.get(key)
        item['first_seen_at']=(old or {}).get('first_seen_at') or item.get('collected_at') or now
        item['last_seen_at']=now
        item['accumulated']=True
        if old and quality_rank(old) > quality_rank(item):
            # Keep the older, stronger transcript-backed evidence, but mark it as seen again.
            kept=dict(old)
            kept['last_seen_at']=now
            kept['collected_at']=item.get('collected_at') or kept.get('collected_at')
            merged[key]=kept
        else:
            merged[key]=item
        if not old:
            newly.append(item)
    if newly:
        HISTORY.parent.mkdir(parents=True, exist_ok=True)
        with HISTORY.open('a', encoding='utf-8') as f:
            for item in newly:
                f.write(json.dumps({'added_at':now, 'key':item_key(item), 'item':item}, ensure_ascii=False)+'\n')
    def sort_key(item):
        return str(item.get('published_at') or item.get('last_seen_at') or item.get('collected_at') or '')
    return sorted(merged.values(), key=sort_key, reverse=True), len(previous), len(newly)

def recompute_common_and_ystats(items, lex):
    agg={}
    for item in items:
        for ticker in item.get('tickers') or []:
            market=(item.get('ticker_markets') or {}).get(ticker) or item.get('region') or 'domestic'
            name=lex.get(market,{}).get(ticker) or ticker
            key=(market,ticker)
            a=agg.setdefault(key, {'region':market,'ticker':ticker,'name':name,'sources':[], 'source_count':0, 'evidence':[]})
            if item.get('source') not in a['sources']:
                a['sources'].append(item.get('source')); a['source_count']=len(a['sources'])
            a['evidence'].append({'source':item.get('source'),'source_role':item.get('source_role'),'title':item.get('title'),'url':item.get('url'),'published_at':item.get('published_at'),'reason':item.get('summary') or '근거 문장 추출 대기','target_price':item.get('target_price') or '출처에서 명시 안 됨','buy_zone':item.get('buy_zone') or '출처에서 명시 안 됨','price_note':item.get('price_note') or '','confidence':item.get('confidence')})
    common=sorted(agg.values(), key=lambda x:(x['source_count'], len(x['evidence'])), reverse=True)
    for c in common:
        c['stance']='복수 출처 추천/관심' if c['source_count']>=2 else '단일 출처 추천/관심'
        targets=[ev['target_price'] for ev in c['evidence'] if ev.get('target_price') and not str(ev['target_price']).startswith('출처')]
        buys=[ev['buy_zone'] for ev in c['evidence'] if ev.get('buy_zone') and not str(ev['buy_zone']).startswith('출처')]
        c['target_price_summary']=', '.join(dict.fromkeys(targets)) if targets else '출처에서 적정가/목표가를 명시하지 않았습니다.'
        c['buy_zone_summary']=', '.join(dict.fromkeys(buys)) if buys else '출처에서 매수가/진입가를 명시하지 않았습니다.'
        c['caution']='출처 발언을 요약한 정보이며, 매수 전 실적·공시·수급·가격을 별도로 확인해야 합니다.'
    ystats_map={}
    for item in items:
        if not str(item.get('source_type','')).startswith('youtube'):
            continue
        ticker_markets=item.get('ticker_markets', {})
        for stat_region in item.get('stock_regions') or [item.get('region','domestic')]:
            region_tickers=[t for t in item.get('tickers', []) if ticker_markets.get(t, stat_region) == stat_region]
            ykey=(stat_region, item.get('channel_id') or item.get('source'))
            ys=ystats_map.setdefault(ykey, {'region':stat_region, 'youtuber':item.get('source'), 'channel_id':item.get('channel_id',''), 'video_count':0, 'short_count':0, 'regular_video_count':0, 'mention_count':0, 'transcript_count':0, 'metadata_count':0, 'ocr_count':0, 'transcript_chars':0, 'ocr_chars':0, 'stocks':{}, 'videos':[]})
            ys['video_count'] += 1
            if item.get('source_type') == 'youtube_short': ys['short_count'] += 1
            else: ys['regular_video_count'] += 1
            if item.get('confidence') == 'transcript': ys['transcript_count'] += 1
            else: ys['metadata_count'] += 1
            ys['transcript_chars'] += int(item.get('transcript_chars') or 0)
            ys['ocr_chars'] += int(item.get('ocr_chars') or 0)
            if item.get('ocr_status') == 'ok': ys['ocr_count'] += 1
            ys['videos'].append({'title':item.get('title'), 'url':item.get('url'), 'published_at':item.get('published_at'), 'tickers':region_tickers, 'confidence':item.get('confidence'), 'transcript_chars':item.get('transcript_chars',0), 'ocr_status':item.get('ocr_status',''), 'ocr_chars':item.get('ocr_chars',0), 'youtube_kind':'short' if item.get('source_type') == 'youtube_short' else 'video'})
            for ticker in region_tickers:
                name=lex.get(stat_region,{}).get(ticker) or ticker
                stock=ys['stocks'].setdefault(ticker, {'ticker':ticker, 'name':name, 'count':0})
                stock['count'] += 1
                ys['mention_count'] += 1
    ystats=[]
    for ys in ystats_map.values():
        ys['stocks']=sorted(ys['stocks'].values(), key=lambda st:st['count'], reverse=True)
        ys['videos']=sorted(ys['videos'], key=lambda v: str(v.get('published_at') or ''), reverse=True)[:30]
        ystats.append(ys)
    ystats=sorted(ystats, key=lambda y:(y['mention_count'], y['video_count']), reverse=True)
    return common, ystats

def main():
    srcs=json.loads(SOURCES.read_text(encoding='utf-8')); lex=json.loads(LEX.read_text(encoding='utf-8'))
    ocr_index=load_ocr_index()
    records=[]
    # 공유된 개별 YouTube 영상은 해당 유튜버 채널로 확장해 최신 영상을 취합한다.
    for ch in youtube_channel_sources(srcs):
        records += collect_youtube_channel(ch)
    for bucket in ['domestic','global','news']:
        for src in srcs.get(bucket,[]):
            typ=src.get('type')
            if typ in ('youtube_channel','youtube_video'):
                continue
            elif typ=='naver_blog_post': records += collect_naver(src)
            elif typ=='rss': records += collect_rss(src)
    now=datetime.now().isoformat(timespec='minutes')
    translation_cache=load_translation_cache()
    current_items=[]
    for r in records:
        source_region=r.get('region','domestic')
        ocr_text, ocr_rec = ocr_text_for(r.get('video_id',''), ocr_index)
        if str(r.get('source_type','')).startswith('youtube') and YOUTUBE_REQUIRE_TRANSCRIPT and r.get('transcript_status') != 'ok':
            text=ocr_text[:12000]
        else:
            text=(r.get('title','')+' '+r.get('summary','')+' '+r.get('text','')+' '+ocr_text)[:24000]
        mentions=detect_all_mentions(text, lex)
        stock_regions=sorted({m['market'] for m in mentions}) or [source_region]
        title=r.get('title') or '제목 없음'; summary=r.get('summary') or '요약 없음'
        price_fields=extract_price_fields(text)
        item={'region':stock_regions[0], 'stock_regions':stock_regions, 'source_region':source_region, 'source':r.get('source'), 'channel_id':r.get('channel_id',''), 'video_id':r.get('video_id',''), 'source_role':infer_source_role(r.get('source_type')), 'source_type':r.get('source_type'), 'title':title, 'summary':summary[:700], 'tickers':[m['ticker'] for m in mentions], 'ticker_markets':{m['ticker']:m['market'] for m in mentions}, 'recommendation':'추천/관심 언급' if mentions else '정보', 'confidence':'transcript' if r.get('transcript_status')=='ok' else ('ocr_only' if ocr_text else ('caption_failed' if str(r.get('source_type','')).startswith('youtube') else 'source-title/meta')), 'url':r.get('url',''), 'published_at':r.get('published_at',''), 'collected_at':now, 'target_price':price_fields['target_price'], 'buy_zone':price_fields['buy_zone'], 'price_note':price_fields['price_note'], 'transcript_method':r.get('transcript_method',''), 'transcript_status':r.get('transcript_status',''), 'transcript_chars':r.get('transcript_chars',0), 'ocr_method':(ocr_rec or {}).get('ocr_method',''), 'ocr_status':(ocr_rec or {}).get('ocr_status',''), 'ocr_chars':(ocr_rec or {}).get('ocr_chars',0), 'ocr_text_path':(ocr_rec or {}).get('ocr_text_path',''), 'extraction_quality':('transcript+ocr' if (r.get('transcript_status')=='ok' and ocr_text) else ('ocr_only' if ocr_text else r.get('extraction_quality','metadata')))}
        current_items.append(item)
    items, previous_count, newly_added = merge_accumulated_items(current_items, now)
    common, ystats = recompute_common_and_ystats(items, lex)
    DATA.write_text(json.dumps(items,ensure_ascii=False,indent=2),encoding='utf-8')
    RAW.write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    COMMON.write_text(json.dumps(common,ensure_ascii=False,indent=2),encoding='utf-8')
    YSTATS.write_text(json.dumps(ystats,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'collected records={len(records)} current_items={len(current_items)} accumulated_items={len(items)} previous={previous_count} new={newly_added} common={len(common)} youtubers={len(ystats)}')
    for c in common[:10]: print(c['region'], c['ticker'], c['name'], c['source_count'], 'evidence=', len(c.get('evidence', [])))
if __name__=='__main__': main()
