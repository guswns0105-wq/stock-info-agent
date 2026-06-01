#!/usr/bin/env python3
"""Extract representative YouTube video frames and OCR visible screen text.

This is intentionally bounded for cron/scheduled use:
- groups current data/items.json by YouTuber/channel
- processes latest N per channel (env STOCK_OCR_MAX_VIDEOS_PER_CHANNEL, default 5)
- extracts a few frames per video (env STOCK_OCR_FRAMES_PER_VIDEO, default 3)
- uses Apple Vision via a small Swift CLI, no remote OCR service
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'items.json'
OUTDIR = ROOT / 'data' / 'youtube_ocr'
INDEX = OUTDIR / 'ocr_index.json'
SWIFT = ROOT / 'scripts' / 'apple_vision_ocr.swift'
YTDLP = shutil.which('yt-dlp') or '/Users/mac1/.hermes-4/home/.local/bin/yt-dlp'
FFMPEG = shutil.which('ffmpeg') or '/opt/homebrew/bin/ffmpeg'

MAX_PER_CHANNEL = int(os.environ.get('STOCK_OCR_MAX_VIDEOS_PER_CHANNEL', '5'))
FRAMES_PER_VIDEO = int(os.environ.get('STOCK_OCR_FRAMES_PER_VIDEO', '3'))
MIN_CHARS = int(os.environ.get('STOCK_OCR_MIN_CHARS', '4'))
VIDEO_HEIGHT = int(os.environ.get('STOCK_OCR_VIDEO_HEIGHT', '720'))
TIMEOUT_DOWNLOAD = int(os.environ.get('STOCK_OCR_DOWNLOAD_TIMEOUT', '180'))
TIMEOUT_FFMPEG = int(os.environ.get('STOCK_OCR_FFMPEG_TIMEOUT', '90'))


def run(cmd, timeout=120, cwd=None):
    return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, cwd=cwd)


def ensure_swift_ocr():
    if not SWIFT.exists():
        SWIFT.write_text(r'''import Foundation
import Vision
import AppKit

if CommandLine.arguments.count < 2 {
    fputs("usage: apple_vision_ocr.swift IMAGE\n", stderr)
    exit(2)
}
let imageURL = URL(fileURLWithPath: CommandLine.arguments[1])
guard let image = NSImage(contentsOf: imageURL), let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    fputs("failed to load image\n", stderr)
    exit(1)
}
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
request.recognitionLanguages = ["ko-KR", "en-US"]
let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
do {
    try handler.perform([request])
    var rows: [[String: Any]] = []
    for obs in request.results ?? [] {
        guard let cand = obs.topCandidates(1).first else { continue }
        rows.append([
            "text": cand.string,
            "confidence": cand.confidence,
            "bbox": [obs.boundingBox.origin.x, obs.boundingBox.origin.y, obs.boundingBox.size.width, obs.boundingBox.size.height]
        ])
    }
    let data = try JSONSerialization.data(withJSONObject: rows, options: [])
    FileHandle.standardOutput.write(data)
} catch {
    fputs("ocr error: \(error)\n", stderr)
    exit(1)
}
''', encoding='utf-8')


def load_items():
    if not DATA.exists():
        return []
    return json.loads(DATA.read_text(encoding='utf-8'))


def item_sort_key(item):
    return str(item.get('published_at') or item.get('last_seen_at') or item.get('collected_at') or '')


def select_items(items):
    groups = {}
    for item in items:
        if not str(item.get('source_type','')).startswith('youtube') or not item.get('video_id'):
            continue
        key = item.get('channel_id') or item.get('source') or 'unknown'
        groups.setdefault(key, []).append(item)
    selected = []
    for key, arr in groups.items():
        arr = sorted(arr, key=item_sort_key, reverse=True)
        selected.extend(arr[:MAX_PER_CHANNEL])
    return selected


def file_sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def existing_index():
    if INDEX.exists():
        try:
            data = json.loads(INDEX.read_text(encoding='utf-8'))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def download_video(video_id, video_path):
    url = 'https://www.youtube.com/watch?v=' + video_id
    fmt = f'bestvideo[height<={VIDEO_HEIGHT}][ext=mp4]+bestaudio[ext=m4a]/best[height<={VIDEO_HEIGHT}][ext=mp4]/best[height<={VIDEO_HEIGHT}]'
    cmd = [YTDLP, '-f', fmt, '--merge-output-format', 'mp4', '--no-playlist', '--ignore-no-formats-error', '--no-warnings', '-o', str(video_path), url]
    return run(cmd, timeout=TIMEOUT_DOWNLOAD)


def extract_frames(video_path, frames_dir, frames_per_video=FRAMES_PER_VIDEO):
    frames_dir.mkdir(parents=True, exist_ok=True)
    # Use evenly-spaced scene-independent sampling through fps expression.
    # Very short Shorts still produce up to FRAMES_PER_VIDEO frames.
    pattern = str(frames_dir / 'frame_%03d.jpg')
    cmd = [FFMPEG, '-hide_banner', '-loglevel', 'error', '-i', str(video_path), '-vf', f'fps={frames_per_video}/60,scale=-1:{VIDEO_HEIGHT}', '-frames:v', str(frames_per_video), '-q:v', '2', pattern]
    proc = run(cmd, timeout=TIMEOUT_FFMPEG)
    frames = sorted(frames_dir.glob('frame_*.jpg'))
    if not frames:
        # fallback: fixed points from beginning/middle-ish
        for idx, sec in enumerate([2, 12, 30][:frames_per_video], 1):
            p = frames_dir / f'frame_{idx:03d}.jpg'
            proc2 = run([FFMPEG, '-hide_banner', '-loglevel', 'error', '-ss', str(sec), '-i', str(video_path), '-frames:v', '1', '-vf', f'scale=-1:{VIDEO_HEIGHT}', '-q:v', '2', str(p)], timeout=TIMEOUT_FFMPEG)
        frames = sorted(frames_dir.glob('frame_*.jpg'))
    return frames, proc


def ocr_frame(frame):
    proc = run(['/usr/bin/swift', str(SWIFT), str(frame)], timeout=90)
    if proc.returncode != 0:
        return [], proc.stderr[-500:]
    try:
        rows = json.loads(proc.stdout or '[]')
    except Exception as e:
        return [], f'json parse failed: {e}'
    rows = [r for r in rows if len(str(r.get('text','')).strip()) >= MIN_CHARS]
    return rows, ''


def process_item(item, index):
    video_id = item['video_id']
    if video_id in index and index[video_id].get('ocr_status') == 'ok':
        return index[video_id] | {'skipped_existing': True}
    vdir = OUTDIR / 'videos' / video_id
    frames_dir = OUTDIR / 'frames' / video_id
    ocr_dir = OUTDIR / 'ocr' / video_id
    logs_dir = OUTDIR / 'logs'
    for d in [vdir, frames_dir, ocr_dir, logs_dir]:
        d.mkdir(parents=True, exist_ok=True)
    video_path = vdir / f'{video_id}.mp4'
    if not video_path.exists() or video_path.stat().st_size < 100_000:
        proc = download_video(video_id, video_path)
        (logs_dir / f'{video_id}.download.log').write_text((proc.stdout or '') + '\n--- STDERR ---\n' + (proc.stderr or ''), encoding='utf-8')
        if proc.returncode != 0 or not video_path.exists():
            return {'video_id': video_id, 'ocr_status': 'download_failed', 'title': item.get('title'), 'source': item.get('source'), 'error': (proc.stderr or proc.stdout)[-700:]}
    frames, proc = extract_frames(video_path, frames_dir)
    (logs_dir / f'{video_id}.ffmpeg.log').write_text((proc.stdout or '') + '\n--- STDERR ---\n' + (proc.stderr or ''), encoding='utf-8')
    if not frames:
        return {'video_id': video_id, 'ocr_status': 'frame_failed', 'title': item.get('title'), 'source': item.get('source'), 'video_path': str(video_path)}
    frame_results = []
    text_parts = []
    errors = []
    for frame in frames[:FRAMES_PER_VIDEO]:
        rows, err = ocr_frame(frame)
        if err:
            errors.append(f'{frame.name}: {err}')
        frame_json = {'frame': str(frame), 'frame_sha256': file_sha(frame), 'rows': rows}
        (ocr_dir / (frame.stem + '.ocr.json')).write_text(json.dumps(frame_json, ensure_ascii=False, indent=2), encoding='utf-8')
        frame_results.append(frame_json)
        for r in rows:
            text_parts.append(str(r.get('text','')).strip())
    # de-dupe while preserving order
    dedup = []
    seen = set()
    for t in text_parts:
        norm = ' '.join(t.split())
        if norm and norm not in seen:
            seen.add(norm); dedup.append(norm)
    ocr_text = '\n'.join(dedup)
    (ocr_dir / 'ocr_text.txt').write_text(ocr_text, encoding='utf-8')
    rec = {
        'video_id': video_id,
        'url': item.get('url') or ('https://youtu.be/' + video_id),
        'source': item.get('source'),
        'channel_id': item.get('channel_id',''),
        'title': item.get('title'),
        'published_at': item.get('published_at',''),
        'ocr_status': 'ok' if ocr_text else 'no_text',
        'ocr_method': 'apple_vision_frame_ocr',
        'ocr_chars': len(ocr_text),
        'frame_count': len(frames[:FRAMES_PER_VIDEO]),
        'ocr_text_path': str(ocr_dir / 'ocr_text.txt'),
        'frames_dir': str(frames_dir),
        'video_path': str(video_path),
        'errors': errors[:5],
        'updated_at': datetime.now().isoformat(timespec='minutes'),
    }
    return rec


def main():
    ensure_swift_ocr()
    OUTDIR.mkdir(parents=True, exist_ok=True)
    items = load_items()
    selected = select_items(items)
    index = existing_index()
    processed = []
    for item in selected:
        rec = process_item(item, index)
        index[item['video_id']] = rec
        processed.append(rec)
        INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding='utf-8')
    ok = [r for r in index.values() if r.get('ocr_status') == 'ok']
    report = {
        'generated_at': datetime.now().isoformat(timespec='minutes'),
        'max_per_channel': MAX_PER_CHANNEL,
        'frames_per_video': FRAMES_PER_VIDEO,
        'selected_this_run': len(selected),
        'processed_this_run': len(processed),
        'index_total': len(index),
        'ok_total': len(ok),
        'total_ocr_chars': sum(int(r.get('ocr_chars') or 0) for r in ok),
        'by_source': {},
    }
    for r in index.values():
        s = r.get('source') or 'unknown'
        b = report['by_source'].setdefault(s, {'items': 0, 'ok': 0, 'chars': 0})
        b['items'] += 1
        if r.get('ocr_status') == 'ok':
            b['ok'] += 1; b['chars'] += int(r.get('ocr_chars') or 0)
    (OUTDIR / 'quality_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"youtube_ocr selected={len(selected)} processed={len(processed)} index_total={len(index)} ok={len(ok)} chars={report['total_ocr_chars']}")
    for source, stats in sorted(report['by_source'].items()):
        print(source, stats)


if __name__ == '__main__':
    main()
