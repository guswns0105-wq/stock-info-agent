#!/usr/bin/env python3
import json
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'/'items.json'; SOURCES=ROOT/'config'/'sources.json'
def main():
    sources=json.loads(SOURCES.read_text(encoding='utf-8')) if SOURCES.exists() else {}
    items=json.loads(DATA.read_text(encoding='utf-8')) if DATA.exists() else []
    now=datetime.now().isoformat(timespec='minutes')
    for item in items:
        if not item.get('collected_at'): item['collected_at']=now
    DATA.write_text(json.dumps(items,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"sources: domestic={len(sources.get('domestic',[]))}, global={len(sources.get('global',[]))}, news={len(sources.get('news',[]))}; items={len(items)}")
if __name__=='__main__': main()
