"""🔍 원본 찾기: 영상(파일 또는 링크)을 넣으면 원본과 비슷한 결의 영상을 찾는다.

1. 영상을 장면이 바뀌는 곳마다 나누고 장면 사진을 뽑는다 (모음 영상이면 장면마다 원본이 다를 수 있음)
2. 말소리를 글자로 바꾸고, AI가 장면과 대사를 보고 원본 검색어와 '비슷한 결' 검색어를 만든다
3. 유튜브에서 원본 후보를 모아 썸네일로 1차 비교하고, 상위 후보는 받아서 2초마다 장면을 맞춰 본다
   → 어느 장면이 원본의 몇 분 몇 초인지, 내 장면/원본 장면을 나란히 볼 수 있는 사진까지 만든다
4. (유료, 선택) 구글 이미지 검색(Cloud Vision)으로 장면마다 인터넷 전체에서 같은 장면을 찾는다
5. 비슷한 결의 영상을 유튜브에서 모은다

장면 사진은 화면의 '구글 렌즈에서 찾기' 버튼(무료)에도 쓰인다.
"""
import glob
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from urllib.parse import urlparse

import requests
from PIL import Image

from . import config, frames, llm, video

SYSTEM = "너는 영상 출처를 찾는 전문가야. 영상 장면을 보고 원본과 비슷한 영상을 찾을 수 있게 분석한다. 반드시 JSON으로만 답한다."

PROMPT = """이 이미지들은 어떤 영상에서 시간 순서대로 뽑은 장면이야.
{speech}
이 영상은 다른 원본 영상(유튜브, 틱톡, 인스타, 방송, 영화, 게임 방송 등)을 가져다 만든 것일 수 있고,
여러 원본을 이어 붙인 모음 영상일 수도 있어.
장면 속 인물, 장소, 화면 글자(자막·로고·워터마크·채널명·틱톡/인스타 아이디), 촬영 방식, 분위기를 아주 자세히 살펴보고 분석해줘.

규칙:
- 화면에 보이는 글자는 그대로 옮겨 적기 (특히 @아이디, 워터마크, 방송사 마크)
- 아는 인물·프로그램·작품이면 이름을 적고, 확실하지 않으면 "추정"이라고 적기
- queries: 원본을 유튜브에서 찾기 위한 검색어 6~8개. 짧고 구체적으로. 해외 영상으로 보이면 영어 검색어 위주.
- trend: 이 영상의 컨셉·유행을 한 문장으로 (예: "번개가 치는 순간에 맞춰 사진을 찍는 챌린지")
- similar_queries: 같은 컨셉·유행의 '다른' 영상을 찾기 위한 검색어 5~6개 (한국어와 영어 섞어서, 해시태그 형태도 좋음)

JSON 형식:
{{"summary": "무슨 영상인지 2~3문장", "source_type": "원본 종류", "guess_title": "원본 제목 추정",
  "people": ["인물"], "on_screen_text": ["화면 글자"], "queries": ["검색어"],
  "trend": "컨셉 한 문장", "similar_queries": ["검색어"]}}"""

PLATFORMS = {"youtube.com": "유튜브", "youtu.be": "유튜브", "tiktok.com": "틱톡", "instagram.com": "인스타",
             "facebook.com": "페이스북", "x.com": "X", "twitter.com": "X", "reddit.com": "레딧",
             "douyin.com": "더우인", "bilibili.com": "빌리빌리", "naver.com": "네이버", "pinterest.": "핀터레스트"}


def _youtube():
    import yt_dlp
    return yt_dlp


def platform_of(url):
    host = urlparse(url).netloc.lower()
    for key, name in PLATFORMS.items():
        if key in host:
            return name
    return host.replace("www.", "")


def is_url(text):
    return str(text).strip().lower().startswith(("http://", "https://"))


# ---------- 0. 링크로 넣은 영상 받기 ----------
def download_input(url, work, progress):
    """링크(유튜브·틱톡·인스타 등)의 영상을 분석용으로 받는다. (경로, 영상 id)"""
    yt = _youtube()

    def hook(d):
        if d.get("status") == "downloading" and d.get("total_bytes"):
            progress(0.01 + 0.04 * d["downloaded_bytes"] / d["total_bytes"], "링크의 영상 받는 중")

    opts = {"quiet": True, "noprogress": True, "format": "b[height<=720][ext=mp4]/bv*[height<=720]+ba/b",
            "merge_output_format": "mp4", "ffmpeg_location": video.ffmpeg(),
            "outtmpl": os.path.join(work, "input.%(ext)s"), "progress_hooks": [hook]}
    try:
        with yt.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url.strip(), download=True)
    except Exception as e:
        raise ValueError("링크의 영상을 받지 못했어요. 비공개 영상이거나 로그인이 필요한 영상일 수 있어요. "
                         "이럴 땐 영상을 파일로 저장해서 넣어 주세요.\n(" + str(e)[:200] + ")")
    paths = glob.glob(os.path.join(work, "input.*"))
    return paths[0], info.get("id"), info.get("title") or ""


# ---------- 1~2. 분석 ----------
def analyze(src, work, settings, progress):
    """장면 나누기 + 대사 + AI 분석. (장면 목록, 비교용 장면, 대사, AI 결과)"""
    progress(0.06, "장면이 바뀌는 곳 찾는 중")
    scenes = frames.scenes(src, os.path.join(work, "scenes"))
    if not scenes:
        raise ValueError("영상에서 장면을 뽑지 못했어요. 영상 파일이 맞는지 확인해 주세요.")
    # 비교용 장면: 장면마다 1장, 너무 적으면 고르게 더 뽑는다
    shots = [(s["time"], s["frame"], s["index"]) for s in scenes]
    if len(shots) < 8:
        extra = frames.extract(src, os.path.join(work, "extra"), count=12 - len(shots))
        for t, p in extra:
            idx = next((s["index"] for s in scenes if s["start"] <= t <= s["end"]), 0)
            shots.append((t, p, idx))
        shots.sort()

    progress(0.1, "말소리 알아듣는 중")
    speech = _speech_with_limit(src, settings, progress)

    progress(0.22, "AI가 장면과 대사를 분석하는 중")
    step = max(1, len(scenes) // 6)
    picks = [s["frame"] for s in scenes[::step]][:6]
    text = " ".join(t for _, _, t in speech)[:1500]
    speech_line = f'영상 속 대사: "{text}"' if text else "영상에 대사는 없어."
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
    info["similar_queries"] = [str(q).strip() for q in info.get("similar_queries", []) if str(q).strip()]
    return scenes, shots, speech, info


def _speech_with_limit(src, settings, progress, limit=90):
    """대사 알아듣기. limit초가 넘으면 거기까지 들은 대사만 가지고 넘어간다.

    말소리가 없거나 음성 인식을 못 써도 장면만으로 계속할 수 있으니 실패해도 괜찮다.
    """
    from . import clip_mode
    heard, done = [], threading.Event()
    started = [None]  # 음성 인식 AI를 다 불러온 뒤부터 시간을 잰다 (처음 내려받는 시간은 빼고)

    def report(frac, msg):
        if started[0] is None and frac >= 0.05:
            started[0] = time.time()
        progress(0.1 + 0.1 * frac, msg)

    def work():
        try:
            clip_mode.transcribe(src, settings, report, out=heard, fast=True)
        except Exception:
            pass
        finally:
            done.set()

    threading.Thread(target=work, daemon=True).start()
    while not done.wait(1):
        if started[0] and time.time() - started[0] > limit:
            progress(0.2, "대사가 길거나 음악이 많아서, 지금까지 들은 대사로 다음 단계로 넘어가요")
            break
    return list(heard)


# ---------- 3. 유튜브 후보 ----------
def search(queries, per_query=8, exclude=()):
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
                if not vid or vid in exclude:
                    continue
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
    qhs = [q for q in (frames.query_hashes(p) for _, p, _ in shots) if q]
    items = list(cands.values())

    def score(c):
        best = min((frames.distance(q, r) for q in qhs for r in _thumb_hashes(c["id"])), default=64)
        c["quick"] = round(max(0.0, (22 - best) / 22) * 100)
        return c

    with ThreadPoolExecutor(8) as pool:
        for i, _ in enumerate(pool.map(score, items)):
            progress(0.42 + 0.13 * (i + 1) / max(len(items), 1), f"후보 썸네일 비교 중 ({i + 1}/{len(items)})")


def _download_small(url, out_dir):
    """정밀 비교용으로 낮은 화질로 받는다."""
    yt = _youtube()
    opts = {"quiet": True, "noprogress": True, "format": "worst[height>=144][ext=mp4]/worst",
            "outtmpl": os.path.join(out_dir, "small.%(ext)s"), "ffmpeg_location": video.ffmpeg()}
    with yt.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)


def deep_check(cand, shots, work, query_len, max_minutes=180):
    """후보 영상을 받아 2초마다 장면 비교.

    채우는 값: deep(같은 장면 비율 %), start/end(원본 속 위치), scenes(장면 번호→원본 시각),
    proofs(내 장면과 원본 장면을 나란히 보여줄 사진)
    """
    if cand["duration"] and cand["duration"] > max_minutes * 60:
        cand["note"] = "너무 길어서 정밀 비교는 건너뛰었어요"
        return
    folder = os.path.join(work, "cand_" + cand["id"])
    os.makedirs(folder, exist_ok=True)
    try:
        small = _download_small(cand["url"], folder)
        refs = [(t, frames.ref_hashes(p), p) for t, p in frames.sample(small, os.path.join(folder, "f"))]
    except Exception:
        cand["note"] = "영상을 받지 못해 정밀 비교를 못 했어요"
        shutil.rmtree(folder, ignore_errors=True)
        return
    qs = [(qt, qh, qp, si) for qt, qp, si in shots if (qh := frames.query_hashes(qp))]
    if not qs or not refs:
        cand["deep"] = 0
        shutil.rmtree(folder, ignore_errors=True)
        return
    every = refs[1][0] - refs[0][0] if len(refs) > 1 else 2.0

    # ① 장면마다 따로 가장 닮은 곳 찾기 (모음 영상처럼 여러 부분을 섞었어도 잡힘)
    matches = []
    for qt, qh, qp, si in qs:
        d, rt, rp = min(((frames.distance(qh, rh), rt, rp) for rt, rh, rp in refs), key=lambda x: x[0])
        if d <= 12:
            matches.append((d, qt, qp, si, rt, rp))

    # ② 시간 순서까지 맞춰 보기: 원본의 어느 지점부터 잘랐는지 1초 단위로 찾는다
    best = (64 * len(qs), 0.0, 0)
    for offset in range(0, int(refs[-1][0]) + 1):
        total, hit = 0, 0
        for qt, qh, _, _ in qs:
            rh = refs[min(len(refs) - 1, max(0, round((qt + offset) / every)))][1]
            d = frames.distance(qh, rh)
            total += d if rh else 20  # 원본 쪽이 검은 화면이면 판단 보류
            hit += d <= 12
        if total < best[0]:
            best = (total, float(offset), hit)
    _, start, aligned = best

    cand["deep"] = round(100 * max(aligned, len(matches) * 0.9) / len(qs))
    # 대부분의 장면이 한 구간에 이어져 맞을 때만 '원본의 몇 분~몇 분'으로 보여준다
    # (모음 영상은 장면마다 위치가 달라서 장면별 위치로만 보여준다)
    if aligned >= len(qs) * 0.6:
        cand["start"] = round(start)
        cand["end"] = round(start + query_len)
    scene_pos = {}
    for d, qt, qp, si, rt, rp in sorted(matches):
        scene_pos.setdefault(si, rt)
    cand["scenes"] = {str(k): round(v) for k, v in sorted(scene_pos.items())}
    # 눈으로 확인할 수 있게 가장 잘 맞은 장면 3쌍을 사진으로 남긴다
    cand["proofs"] = [{"scene": si, "mine": frames.data_uri(qp, 240), "orig": frames.data_uri(rp, 240),
                       "time": round(rt)}
                      for d, qt, qp, si, rt, rp in sorted(matches)[:3]]
    shutil.rmtree(folder, ignore_errors=True)


# ---------- 4. 인터넷 전체 이미지 검색 (유료, 선택) ----------
def web_detect(image_path, key):
    """구글 Cloud Vision '웹 감지'로 같은 장면이 있는 인터넷 페이지를 찾는다."""
    import base64
    with open(image_path, "rb") as f:
        content = base64.b64encode(f.read()).decode("ascii")
    res = requests.post(
        "https://vision.googleapis.com/v1/images:annotate",
        params={"key": key},
        json={"requests": [{"image": {"content": content},
                            "features": [{"type": "WEB_DETECTION", "maxResults": 15}]}]},
        timeout=30,
    )
    data = res.json()
    if res.status_code != 200 or "error" in data:
        msg = data.get("error", {}).get("message", res.text[:200])
        raise llm.LLMError(f"구글 이미지 검색 오류: {msg}")
    web = (data.get("responses") or [{}])[0].get("webDetection", {})
    pages = [{"url": p["url"], "title": p.get("pageTitle", "").replace("<b>", "").replace("</b>", ""),
              "platform": platform_of(p["url"])}
             for p in web.get("pagesWithMatchingImages", []) if p.get("url")]
    return {"pages": pages[:10],
            "words": [e["description"] for e in web.get("webEntities", []) if e.get("description")][:6]}


def web_search_scenes(scenes, key, progress, limit=8):
    """장면마다 인터넷 전체 검색. 비용을 아끼려고 최대 limit개 장면만."""
    step = max(1, len(scenes) // limit)
    targets = scenes[::step][:limit]
    for i, s in enumerate(targets):
        progress(0.86 + 0.1 * i / len(targets), f"인터넷 전체에서 장면 검색 중 ({i + 1}/{len(targets)})")
        try:
            s["web"] = web_detect(s["frame"], key)
        except Exception as e:
            s["web"] = {"error": str(e)[:200], "pages": [], "words": []}


# ---------- 전체 과정 ----------
def _clean_old_runs():
    for old in glob.glob(os.path.join(config.WORK_DIR, "find_*")):
        shutil.rmtree(old, ignore_errors=True)


def find(source, settings, progress=lambda f, d: None, deep_top=5):
    """원본 찾기 전체 과정. source는 파일 경로 또는 링크. 결과 dict를 돌려준다."""
    _clean_old_runs()  # 지난번 결과의 장면 사진은 지운다 (이번 결과는 다음 검색 때까지 남김)
    work = config.new_work_dir("find_" + time.strftime("%Y%m%d_%H%M%S"))
    input_id, input_title = None, ""
    if is_url(source):
        progress(0.01, "링크의 영상 받는 중")
        src, input_id, input_title = download_input(source, work, progress)
    else:
        src = source
    query_len = video.duration(src)
    scenes, shots, speech, info = analyze(src, work, settings, progress)

    progress(0.3, f"유튜브에서 원본 후보 찾는 중 (검색어 {len(info['queries'])}개)")
    exclude = {input_id} if input_id else set()
    cands = search(info["queries"], exclude=exclude)
    ranked = []
    if cands:
        quick_score(cands, shots, progress)
        ranked = sorted(cands.values(), key=lambda c: (c["quick"], c["hits"]), reverse=True)
        top = ranked[:deep_top]
        for i, c in enumerate(top):
            progress(0.56 + 0.22 * i / len(top), f"정밀 비교 중 ({i + 1}/{len(top)}): {c['title'][:30]}")
            deep_check(c, shots, work, query_len)
        for c in ranked:
            c["score"] = c.get("deep", round(c["quick"] * 0.6))
        ranked.sort(key=lambda c: c["score"], reverse=True)

    progress(0.8, "비슷한 결의 영상 찾는 중")
    taken = exclude | {c["id"] for c in ranked if c["score"] >= 30}
    similar = sorted(search(info["similar_queries"], per_query=6, exclude=taken).values(),
                     key=lambda c: (c["hits"], c["views"]), reverse=True)[:24]

    key = settings.get("vision_key", "").strip()
    if key:
        web_search_scenes(scenes, key, progress)

    for s in scenes:  # 화면에 보여줄 장면 사진
        s["image"] = frames.data_uri(s["frame"])
    progress(1, "완료!")
    return {"analysis": info, "speech": " ".join(t for _, _, t in speech), "duration": round(query_len),
            "input": {"title": input_title or os.path.basename(src), "url": source if is_url(source) else ""},
            "scenes": scenes, "candidates": ranked[:20], "similar": similar, "web_search": bool(key)}


def download_original(url, settings, progress=lambda f, d: None):
    """찾은 원본을 좋은 화질(최대 1080p)로 받아 '원본' 폴더에 저장한다. 유튜브 외 사이트도 대부분 된다."""
    yt = _youtube()
    folder = os.path.join(config.output_dir(settings), "원본")
    os.makedirs(folder, exist_ok=True)

    def hook(d):
        if d.get("status") == "downloading" and d.get("total_bytes"):
            progress(d["downloaded_bytes"] / d["total_bytes"] * 0.95, "원본 영상 받는 중")

    opts = {"quiet": True, "noprogress": True,
            "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/bv*[height<=1080]+ba/b",
            "merge_output_format": "mp4", "ffmpeg_location": video.ffmpeg(),
            "outtmpl": os.path.join(folder, "%(title).60s [%(id)s].%(ext)s"),
            "progress_hooks": [hook]}
    try:
        with yt.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = os.path.splitext(ydl.prepare_filename(info))[0] + ".mp4"
    except Exception as e:
        raise ValueError("영상을 받지 못했어요. 비공개이거나 로그인이 필요한 영상일 수 있어요. "
                         "'열기'로 직접 확인해 주세요.\n(" + str(e)[:200] + ")")
    progress(1, "다운로드 완료!")
    return path
