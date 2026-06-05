# Stock Info Agent

매일 오전 8시에 유튜버·블로거·뉴스 소스를 취합해 `public/index.html` 대시보드를 생성하고 GitHub Pages로 공개하는 주식 정보 에이전트입니다.

## 현재 출력 방식

- 국내/해외 탭 분리
- 종목별로 “누가 / 언제 / 왜 추천·언급했는지” 정리
- 블로거·유튜버·뉴스 출처와 원문 링크 표시
- 유튜브 채널은 채널별 `latest_limit` 범위의 최신 작은 창만 확인하고, 이미 누적된 `video_id`는 자막/ASR/OCR 재수집을 건너뜁니다. 경제사냥꾼처럼 쇼츠 주력 채널은 `prefer_shorts: true`로 쇼츠 중심 최신 창만 확인합니다.
- 정밀 YouTube 수집: 자막 캐시 → youtube-transcript-api → yt-dlp 자막/자동자막 순으로 저속 시도하고, 자막·화면 OCR·제목/설명 참고를 근거 강도로 나눠 표시합니다.
- 유튜브 화면 OCR: 각 유튜버 최신 콘텐츠에서 대표 프레임을 추출하고 Apple Vision OCR로 차트/화면 텍스트를 누적해 자막 분석에 보강합니다.
- 원문에 적정가·목표가·매수/진입 구간이 명시된 경우만 가격 표시
- 가격이 원문에 없으면 임의 추정하지 않고 “출처에서 명시 안 됨”으로 표시
- 정보 취합용이며 투자 자문이 아닙니다.

## 소스 추가 위치

`config/sources.json`에 유튜브 채널, 개별 영상, 블로그/RSS를 추가합니다.

## 수집 실행

```bash
# 정밀 YouTube 수집 기본값: 최신 작은 창, 기존 video_id 스킵, 저속 자막 호출
python3 scripts/collect_sources.py
STOCK_OCR_MAX_VIDEOS_PER_CHANNEL=8 STOCK_OCR_FRAMES_PER_VIDEO=5 python3 scripts/ocr_youtube_frames.py
python3 scripts/collect_sources.py
python3 scripts/collect_valuations.py
python3 scripts/build_dashboard.py

# 필요 시 조정
STOCK_YOUTUBE_LATEST_LIMIT=8 STOCK_PRECISE_YOUTUBE=1 STOCK_TRANSCRIPT_WORKERS=1 STOCK_YOUTUBE_CHANNEL_DELAY=8 STOCK_YOUTUBE_TRANSCRIPT_DELAY=3 python3 scripts/collect_sources.py
```
