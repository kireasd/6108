"""🔍 원본 찾기: 쇼츠를 넣으면 그 쇼츠에 쓰인 원본 영상(유튜브)을 찾는다.

1. 쇼츠에서 장면 12장을 뽑고, 말소리를 글자로 바꾼다
2. AI가 장면과 대사를 보고 무슨 영상인지 분석해서 검색어를 만든다
3. 유튜브에서 후보를 모은다
4. 후보 썸네일과 장면을 비교해서 1차로 줄 세운다
5. 상위 후보는 영상을 받아서 2초마다 장면을 비교한다 (정밀 비교)
   → 원본의 몇 분 몇 초 부분인지도 알아낸다
"""
import os
import shutil
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import requests
from PIL import Image

from . import config, frames, llm, video

SYSTEM = "너는 영상 출처를 찾는 전문가야. 쇼츠 장면을 보고 원본 영상을 유튜브에서 찾을 수 있게 분석한다. 반드시 JSON으로만 답한다."

PROMPT = """이 이미지들은 어떤 쇼츠 영상에서 시간 순서대로 고르게 뽑은 장면이야.
{speech}
이 쇼츠는 다른 원본 영상(유튜브 영상, 방송, 영화, 드라마, 예능, 게임 방송, 뉴스 등)을 잘라 만든 것일 가능성이 높아.
장면 속 인물, 장소, 화면 글자(자막·로고·채널명·방송사 마크), 분위기를 아주 자세히 살펴보고 원본을 찾을 수 있게 분석해줘.

규칙:
- 화면에 보이는 글자는 그대로 옮겨 적기 (쇼츠 제작자가 덧붙인 제목/자막과 원본에 있던 글자를 구분)
- 아는 인물·프로그램·작품이면 이름을 적고, 확실하지 않으면 "추정"이라고 적기
- queries: 유튜브에서 원본을 찾기 위한 검색어 6~8개. 짧고 구체적으로. 한국어 위주, 해외 영상이면 영어도.
  (예: 프로그램명 + 회차/장면 설명, 인물 이름 + 상황, 대사 일부)

JSON 형식:
{{"summary": "무슨 영상인지 2~3문장", "source_type": "원본 종류", "guess_title": "원본 제목 추정",
  "people": ["인물"], "on_screen_text": ["화면 글자"], "queries": ["검색어"]}}"""


def _youtube():
    import yt_dlp
    return yt_dlp


def analyze(src, work, settings, progress):
    """쇼츠를 분석한다. (장면 목록, 대사 목록, AI 분석 결과)"""
    progress(0.03, "쇼츠에서 장면 뽑는 중")
    shots = frames.extract(src, os.path.join(work, "query"), count=12)
    if not shots:
        raise ValueError("영상에서 장면을 뽑지 못했어요. 영상 파일이 맞는지 확인해 주세요.")

    progress(0.08, "쇼츠 속 말소리 알아듣는 중")
    speech = []
    try:
        from . import clip_mode
        speech = clip_mode.transcribe(src, settings, lambda f, d: progress(0.08 + 0.12 * f, d))
    except Exception:
        pass  # 말소리가 없거나 음성 인식을 못 써도 장면만으로 계속한다

    progress(0.22, "AI가 장면과 대사를 분석하는 중")
    picks = [p for _, p in shots[::2]]  # 6장만 보여줘도 충분
    text = " ".join(t for _, _, t in speech)[:1500]
    speech_line = f'쇼츠 속 대사: "{text}"' if text else "쇼츠에 대사는 없어."
    try:
        info = llm.ask_json(settings, PROMPT.format(speech=speech_line), SYSTEM, images=picks)
    except llm.LLMError as e:
        if not text:
            raise
        info = {"summary": f"(AI 분석 실패: {e}) 대사로만 찾아요.", "queries": []}
    queries = [str(q).strip() for q in info.get("queries", []) if str(q).strip()]
    # 대사 그대로 검색하면 원본이 잘 나오는 경우가 많다
    longest = sorted((t for _, _, t in speech if len(t) >= 8), key=len, reverse=True)[:2]
    queries += [f'"{t[:60]}"' for t in longest]
    if not queries:
        raise ValueError("검색어를 만들지 못했어요. 다른 AI를 골라 다시 시도해 주세요.")
    info["queries"] = list(dict.fromkeys(queries))
    return shots, speech, info


def search(queries, per_query=8):
    """유튜브에서 후보 영상을 모은다. {id: 후보}"""
    yt = _youtube()
    found = {}
    opts = {"quiet": True, "extract_flat": True, "skip_download": True, "noprogress": True}
    with yt.YoutubeDL(opts) as ydl:
        for q in queries:
            try:
                result = ydl.extract_info(f"ytsearch{per_query}:{q}", download=False)
            except Exception:
                continue
            for e in result.get("entries") or []:
                vid = e.get("id")
                if not vid or vid in found:
                    if vid in found:
                        found[vid]["hits"] += 1
                    continue
                found[vid] = {
                    "id": vid,
                    "title": e.get("title") or "",
                    "channel": e.get("channel") or e.get("uploader") or "",
                    "duration": e.get("duration") or 0,
                    "views": e.get("view_count") or 0,
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    "thumb": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                    "query": q,
                    "hits": 1,
                }
    return found


def _thumb_hashes(vid):
    """유튜브 썸네일 4장(대표 + 자동 장면 3장)의 지문."""
    hashes = []
    for name in ("hqdefault", "1", "2", "3"):
        try:
            res = requests.get(f"https://i.ytimg.com/vi/{vid}/{name}.jpg", timeout=10)
            res.raise_for_status()
            img = Image.open(BytesIO(res.content)).convert("RGB")
        except Exception:
            continue
        w, h = img.size
        if abs(w / h - 4 / 3) < 0.05:  # 4:3 썸네일의 위아래 검은 띠 제거
            img = frames._aspect_crop(img, 16 / 9)
        buf = BytesIO()
        img.save(buf, "JPEG")
        buf.seek(0)
        hashes.append(frames.ref_hashes(buf))
    return [h for h in hashes if h]


def quick_score(cands, shots, progress):
    """썸네일로 1차 점수 (0~100)."""
    qhs = [frames.query_hashes(p) for _, p in shots]
    qhs = [q for q in qhs if q]
    items = list(cands.values())

    def score(c):
        best = min((frames.distance(q, r) for q in qhs for r in _thumb_hashes(c["id"])), default=64)
        c["quick"] = round(max(0.0, (22 - best) / 22) * 100)
        return c

    with ThreadPoolExecutor(8) as pool:
        for i, _ in enumerate(pool.map(score, items)):
            progress(0.45 + 0.15 * (i + 1) / max(len(items), 1), f"후보 썸네일 비교 중 ({i + 1}/{len(items)})")


def _download_small(url, out_dir):
    """정밀 비교용으로 낮은 화질로 받는다."""
    yt = _youtube()
    opts = {"quiet": True, "noprogress": True, "format": "worst[height>=144][ext=mp4]/worst",
            "outtmpl": os.path.join(out_dir, "small.%(ext)s"), "ffmpeg_location": video.ffmpeg()}
    with yt.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)


def deep_check(cand, shots, work, query_len, max_minutes=180):
    """후보 영상을 받아서 2초마다 장면 비교. 몇 %가 같은지와 원본 속 위치를 채운다."""
    if cand["duration"] and cand["duration"] > max_minutes * 60:
        cand["note"] = "너무 길어서 정밀 비교는 건너뛰었어요"
        return
    folder = os.path.join(work, "cand_" + cand["id"])
    os.makedirs(folder, exist_ok=True)
    try:
        small = _download_small(cand["url"], folder)
        refs = [(t, frames.ref_hashes(p)) for t, p in frames.sample(small, os.path.join(folder, "f"))]
    except Exception:
        cand["note"] = "영상을 받지 못해 정밀 비교를 못 했어요"
        return
    every = refs[1][0] - refs[0][0] if len(refs) > 1 else 2.0
    qs = [(qt, qh) for qt, qp in shots if (qh := frames.query_hashes(qp))]
    if not qs or not refs:
        cand["deep"] = 0
        return

    # ① 장면마다 따로 가장 닮은 곳 찾기 (쇼츠가 여러 부분을 섞었어도 잡힘)
    loose = sum(1 for _, qh in qs if min(frames.distance(qh, rh) for _, rh in refs) <= 12)

    # ② 시간 순서까지 맞춰 보기: 원본의 어느 지점부터 잘랐는지 1초 단위로 찾는다
    last = refs[-1][0]
    best = (64 * len(qs), 0.0, 0)
    for offset in range(0, int(last) + 1):
        total, hit = 0, 0
        for qt, qh in qs:
            idx = min(len(refs) - 1, max(0, round((qt + offset) / every)))
            rh = refs[idx][1]
            d = frames.distance(qh, rh)
            total += d if rh else 20  # 원본 쪽이 검은 화면이면 판단 보류
            hit += d <= 12
        if total < best[0]:
            best = (total, float(offset), hit)
    _, start, aligned = best

    cand["deep"] = round(100 * max(aligned, loose * 0.9) / len(qs))
    if aligned >= len(qs) * 0.3:
        cand["start"] = round(start)
        cand["end"] = round(start + query_len)
    shutil.rmtree(folder, ignore_errors=True)


def find(src, settings, progress=lambda f, d: None, deep_top=5):
    """원본 찾기 전체 과정. 결과 dict를 돌려준다."""
    work = config.new_work_dir("find_" + time.strftime("%Y%m%d_%H%M%S"))
    query_len = video.duration(src)
    shots, speech, info = analyze(src, work, settings, progress)

    progress(0.3, f"유튜브에서 후보 찾는 중 (검색어 {len(info['queries'])}개)")
    cands = search(info["queries"])
    if not cands:
        raise ValueError("유튜브에서 후보를 찾지 못했어요. 인터넷 연결을 확인하거나 다른 AI로 다시 시도해 주세요.")

    quick_score(cands, shots, progress)
    ranked = sorted(cands.values(), key=lambda c: (c["quick"], c["hits"]), reverse=True)

    top = ranked[:deep_top]
    for i, c in enumerate(top):
        progress(0.62 + 0.36 * i / len(top), f"정밀 비교 중 ({i + 1}/{len(top)}): {c['title'][:30]}")
        deep_check(c, shots, work, query_len)

    for c in ranked:
        c["score"] = c.get("deep", round(c["quick"] * 0.6))
    ranked.sort(key=lambda c: c["score"], reverse=True)
    shutil.rmtree(work, ignore_errors=True)
    progress(1, "완료!")
    return {"analysis": info, "speech": " ".join(t for _, _, t in speech), "candidates": ranked[:20],
            "duration": round(query_len)}


def download_original(url, settings, progress=lambda f, d: None):
    """찾은 원본을 좋은 화질(최대 1080p)로 받아 '원본' 폴더에 저장한다."""
    yt = _youtube()
    folder = os.path.join(config.output_dir(settings), "원본")
    os.makedirs(folder, exist_ok=True)

    def hook(d):
        if d.get("status") == "downloading" and d.get("total_bytes"):
            progress(d["downloaded_bytes"] / d["total_bytes"] * 0.95, "원본 영상 받는 중")

    opts = {"quiet": True, "noprogress": True,
            "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/b",
            "merge_output_format": "mp4", "ffmpeg_location": video.ffmpeg(),
            "outtmpl": os.path.join(folder, "%(title).60s [%(id)s].%(ext)s"),
            "progress_hooks": [hook]}
    with yt.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = os.path.splitext(ydl.prepare_filename(info))[0] + ".mp4"
    progress(1, "다운로드 완료!")
    return path
