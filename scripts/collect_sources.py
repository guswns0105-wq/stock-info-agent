#!/usr/bin/env python3
import json, re, html, hashlib, urllib.request, urllib.parse, xml.etree.ElementTree as ET
import os, shutil, subprocess, tempfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PACK_ROOT=Path('/Users/mac1/opencrab-local-packs/opencrab-portable-20260531-145915')
DATA=ROOT/'data'/'items.json'; RAW=ROOT/'data'/'raw_sources.json'; COMMON=ROOT/'data'/'common_recommendations.json'; PACKCTX=ROOT/'data'/'local_pack_context.json'
TRANSCRIPTS=ROOT/'data'/'transcripts'
SOURCES=ROOT/'config'/'sources.json'; LEX=ROOT/'config'/'stocks_lexicon.json'
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X) Hermes Stock Agent/1.0'

class TextExtractor(HTMLParser):
    def __init__(self): super().__init__(); self.skip=False; self.parts=[]; self.title=''
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
    """Convert WebVTT/SRV text to readable transcript text."""
    lines=[]
    for line in vtt_text.splitlines():
        line=line.strip()
        if not line or line == 'WEBVTT' or line.startswith('Kind:') or line.startswith('Language:'):
            continue
        if '-->' in line or re.fullmatch(r'\d+', line):
            continue
        line=re.sub(r'<[^>]+>', ' ', line)
        line=html.unescape(line)
        line=' '.join(line.split())
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    return ' '.join(lines)

def get_youtube_transcript(video_id):
    """Fetch captions for normal videos or Shorts. Returns (text, method, status)."""
    TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
    cache=TRANSCRIPTS/f'{video_id}.txt'
    meta=TRANSCRIPTS/f'{video_id}.json'
    if cache.exists() and cache.stat().st_size > 20:
        return cache.read_text(encoding='utf-8', errors='ignore'), 'cache', 'ok'
    url='https://www.youtube.com/watch?v='+video_id
    errors=[]
    # 1) youtube-transcript-api: best when YouTube does not block the IP.
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api=YouTubeTranscriptApi()
        fetched=api.fetch(video_id, languages=['ko','en'])
        text=' '.join(snippet.text for snippet in fetched if getattr(snippet, 'text', '').strip())
        if len(text) > 20:
            cache.write_text(text, encoding='utf-8')
            meta.write_text(json.dumps({'video_id':video_id,'method':'youtube_transcript_api','status':'ok'}, ensure_ascii=False, indent=2), encoding='utf-8')
            return text, 'youtube_transcript_api', 'ok'
    except Exception as e:
        errors.append('youtube_transcript_api: '+str(e).split('\n')[0][:220])
    # 2) yt-dlp subtitles/auto captions fallback. Works for normal videos and Shorts when captions exist.
    ytdlp=shutil.which('yt-dlp') or '/Users/mac1/.hermes-4/home/.local/bin/yt-dlp'
    if os.path.exists(ytdlp):
        with tempfile.TemporaryDirectory() as td:
            outtmpl=str(Path(td)/'%(id)s.%(ext)s')
            cmd=[ytdlp,'--cookies-from-browser','chrome','--skip-download','--write-auto-subs','--write-subs','--sub-langs','ko,en','--sub-format','vtt','--sleep-subtitles','2','--retries','3','--no-warnings','-o',outtmpl,url]
            try:
                env=os.environ.copy(); env.setdefault('HOME', '/Users/mac1'); env['HOME']='/Users/mac1'
                proc=subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90, env=env)
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
    meta.write_text(json.dumps({'video_id':video_id,'method':'none','status':'failed','errors':errors}, ensure_ascii=False, indent=2), encoding='utf-8')
    return '', 'none', status

def collect_youtube_channel(src):
    cid=src.get('channel_id') or src['url'].split('/channel/')[1].split('?')[0].split('/')[0]
    feed=f'https://www.youtube.com/feeds/videos.xml?channel_id={cid}'
    out=[]
    try:
        final,ctype,b=fetch(feed)
        root=ET.fromstring(b)
        ns={'a':'http://www.w3.org/2005/Atom','yt':'http://www.youtube.com/xml/schemas/2015','m':'http://search.yahoo.com/mrss/'}
        for e in root.findall('a:entry',ns)[:8]:
            vid=(e.findtext('yt:videoId', default='', namespaces=ns) or '').strip()
            title=e.findtext('a:title', default='', namespaces=ns)
            published=e.findtext('a:published', default='', namespaces=ns)
            desc=''
            mg=e.find('m:group',ns)
            if mg is not None: desc=mg.findtext('m:description', default='', namespaces=ns)
            transcript, method, status = get_youtube_transcript(vid) if vid else ('', 'none', 'no video id')
            is_short = '#shorts' in (title+' '+desc).lower() or '/shorts/' in src.get('url','')
            summary = (transcript[:900] if transcript else desc[:500])
            if not transcript:
                summary = (summary + ' | 자막추출 실패/없음: ' + status[:180])[:900]
            out.append({'source':src['name'],'source_type':'youtube_short' if is_short else 'youtube_video','region':src.get('region','domestic'),'title':title,'summary':summary,'url':'https://youtu.be/'+vid if vid else src['url'],'published_at':published,'text':title+' '+desc+' '+transcript,'transcript_method':method,'transcript_status':'ok' if transcript else status})
    except Exception as e:
        out.append({'source':src['name'],'source_type':'youtube_channel','region':src.get('region','domestic'),'title':'수집 실패','summary':str(e),'url':src['url'],'published_at':'','text':'','transcript_method':'none','transcript_status':'channel feed failed'})
    return out

def collect_youtube_video(src):
    vid=src.get('video_id') or src['url'].split('youtu.be/')[1].split('?')[0].split('/')[0]
    title=yt_oembed(vid) or src['name']
    transcript, method, status = get_youtube_transcript(vid)
    is_short = '/shorts/' in src.get('url','')
    summary = transcript[:900] if transcript else '자막추출 실패/없음: '+status[:500]
    return [{'source':src['name'],'source_type':'youtube_short' if is_short else 'youtube_video','region':src.get('region','global'),'title':title,'summary':summary,'url':'https://youtu.be/'+vid,'published_at':'','text':title+' '+transcript,'transcript_method':method,'transcript_status':'ok' if transcript else status}]

def collect_naver(src):
    try:
        final,ctype,b=fetch(src['url'])
        text=visible_text(b)
        # try iframe PostView when homepage wrapper
        m=re.search(r'logNo\s*=\s*["\']?(\d+)', b.decode('utf-8','ignore')) or re.search(r'/PostView\.naver\?[^"\']*logNo=(\d+)', b.decode('utf-8','ignore'))
        if m:
            parsed=urllib.parse.urlparse(src['url']); blog=parsed.path.strip('/').split('/')[0]
            pv=f'https://blog.naver.com/PostView.naver?blogId={blog}&logNo={m.group(1)}&redirect=Dlog&widgetTypeCall=true&directAccess=false'
            try:
                final2,_,b2=fetch(pv); t2=visible_text(b2)
                if len(t2)>len(text): final,text=final2,t2
            except Exception: pass
        title=text[:80]
        return [{'source':src['name'],'source_type':'naver_blog_post','region':src.get('region','domestic'),'title':title or src['name'],'summary':text[:700],'url':src['url'],'published_at':'','text':text}]
    except Exception as e:
        return [{'source':src['name'],'source_type':'naver_blog_post','region':src.get('region','domestic'),'title':'수집 실패','summary':str(e),'url':src['url'],'published_at':'','text':''}]

def collect_rss(src):
    out=[]
    try:
        final,ctype,b=fetch(src['url']); root=ET.fromstring(b)
        items=root.findall('.//item')[:5]
        if items:
            for it in items:
                title=it.findtext('title') or ''; desc=it.findtext('description') or ''; link=it.findtext('link') or src['url']; pub=it.findtext('pubDate') or ''
                out.append({'source':src['name'],'source_type':'rss','region':src.get('region','domestic'),'title':title,'summary':re.sub('<[^>]+>',' ',desc)[:500],'url':link,'published_at':pub,'text':title+' '+re.sub('<[^>]+>',' ',desc)})
    except Exception as e:
        out.append({'source':src['name'],'source_type':'rss','region':src.get('region','domestic'),'title':'수집 실패','summary':str(e),'url':src['url'],'published_at':'','text':''})
    return out

def collect_local_pack(pack_id, region):
    base=PACK_ROOT/'expanded-packs'/pack_id
    chunks=[]
    for rel in ['00_index/evidence_index.jsonl','00_index/chunk_index.jsonl','opencrab_pack.md','README.md','06_reports/pack_description.md']:
        p=base/rel
        if not p.exists(): continue
        txt=p.read_text(encoding='utf-8',errors='ignore')[:50000]
        for kw in ['종목','stock','selection','market','투자','리스크','섹터','theme','ticker']:
            i=txt.lower().find(kw.lower())
            if i>=0:
                chunks.append(txt[max(0,i-350):i+650]); break
    return {'pack_id':pack_id,'region':region,'evidence':chunks[:5]}

def detect_mentions(text, lex_region):
    mentions=[]; low=text.lower()
    for code,name in lex_region.items():
        hit=False
        if re.search(r'(?<![A-Z0-9])'+re.escape(code)+r'(?![A-Z0-9])', text): hit=True
        if name and name.lower() in low: hit=True
        # NAVER 블로그 UI의 영문 NAVER 반복은 035420 종목 언급으로 보지 않음
        if code == '035420' and '네이버' not in text and not re.search(r'(?<![A-Z0-9])035420(?![A-Z0-9])', text):
            hit = False
        if hit: mentions.append({'ticker':code,'name':name})
    return mentions

def main():
    srcs=json.loads(SOURCES.read_text(encoding='utf-8')); lex=json.loads(LEX.read_text(encoding='utf-8'))
    records=[]
    for bucket in ['domestic','global','news']:
        for src in srcs.get(bucket,[]):
            typ=src.get('type')
            if typ=='youtube_channel': records += collect_youtube_channel(src)
            elif typ=='youtube_video': records += collect_youtube_video(src)
            elif typ=='naver_blog_post': records += collect_naver(src)
            elif typ=='rss': records += collect_rss(src)
    pack_context=[collect_local_pack(p['pack_id'],p.get('region','domestic')) for p in srcs.get('local_packs',[])]
    now=datetime.now().isoformat(timespec='minutes')
    items=[]; agg={}
    for r in records:
        region=r.get('region','domestic')
        text=(r.get('title','')+' '+r.get('summary','')+' '+r.get('text',''))[:10000]
        mentions=detect_mentions(text, lex.get(region,{}))
        # add global detection fallback for global names appearing in domestic sources too
        if region=='domestic': mentions += [m for m in detect_mentions(text, lex.get('global',{})) if m not in mentions]
        for m in mentions:
            key=(region,m['ticker'])
            a=agg.setdefault(key, {'region':region,'ticker':m['ticker'],'name':m['name'],'sources':[], 'source_count':0, 'evidence':[]})
            if r['source'] not in a['sources']: a['sources'].append(r['source']); a['source_count']=len(a['sources'])
            a['evidence'].append({'source':r['source'],'title':r['title'],'url':r['url']})
        title=r.get('title') or '제목 없음'
        summary=r.get('summary') or '요약 없음'
        items.append({'region':region,'source':r.get('source'), 'source_type':r.get('source_type'), 'title':title, 'summary':summary[:700], 'tickers':[m['ticker'] for m in mentions], 'recommendation':'공통관심 후보' if mentions else '정보', 'confidence':'transcript' if r.get('transcript_status')=='ok' else 'source-title/meta', 'url':r.get('url',''), 'published_at':r.get('published_at',''), 'collected_at':now, 'transcript_method':r.get('transcript_method',''), 'transcript_status':r.get('transcript_status','')})
    common=sorted(agg.values(), key=lambda x:(x['source_count'], len(x['evidence'])), reverse=True)
    # enrich with local pack context notes, not direct recs
    for c in common:
        region=c['region']; relevant=[p for p in pack_context if p['region']==region and p['evidence']]
        c['local_pack_notes']=[{'pack_id':p['pack_id'],'note':p['evidence'][0][:300]} for p in relevant[:2]]
        c['stance']='여러 소스에서 반복 언급된 관심 종목' if c['source_count']>=2 else '단일/메타데이터 언급 종목'
        c['risk']='로컬팩 원칙상 출처 반복 언급은 매수 근거가 아니며, 최신 실적·수급·뉴스 확인 필요'
    DATA.write_text(json.dumps(items,ensure_ascii=False,indent=2),encoding='utf-8')
    RAW.write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    COMMON.write_text(json.dumps(common,ensure_ascii=False,indent=2),encoding='utf-8')
    PACKCTX.write_text(json.dumps(pack_context,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'collected records={len(records)} items={len(items)} common={len(common)} packs={len(pack_context)}')
    for c in common[:10]: print(c['region'], c['ticker'], c['name'], c['source_count'])
if __name__=='__main__': main()
