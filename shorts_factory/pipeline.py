"""딸깍 파이프라인: 다운로드 → 자막 확보 → AI 각색 → FFmpeg 렌더."""
import glob
import json
import os
import re
import shutil
import subprocess
from datetime import datetime

from PIL import ImageFont

import subtitles as subs
from config import OUTPUT_DIR, WORK_DIR, find_font

W, H = 1080, 1920


class JobError(Exception):
    pass


# Windows에서 ffmpeg 실행 시 검은 창이 뜨지 않게
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run(cmd, cwd=None):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="ignore",
                       creationflags=_NO_WINDOW)
    if p.returncode != 0:
        raise JobError(f"{os.path.basename(cmd[0])} 실패:\n{p.stderr[-1500:]}")
    return p.stdout


def probe(path):
    out = _run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path])
    info = json.loads(out)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    if not v:
        raise JobError("영상 스트림이 없습니다.")
    has_audio = any(s["codec_type"] == "audio" for s in info["streams"])
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        rot = abs(int(sd.get("rotation", 0) or 0))
    w, h = int(v["width"]), int(v["height"])
    if rot in (90, 270):
        w, h = h, w
    return {"w": w, "h": h, "duration": float(info["format"].get("duration", 0)), "has_audio": has_audio}


# ---------- 1. 소스 확보 ----------

_BROWSERS = ["firefox", "edge", "chrome", "whale", "brave", "opera"]


def _is_age(msg):
    m = msg.lower()
    return "confirm your age" in m or "age-restricted" in m or "age restricted" in m


def _needs_login(msg):
    return "Sign in to confirm" in msg or "not a bot" in msg or _is_age(msg)


def _friendly(err):
    """yt-dlp 오류를 쉬운 한국어로."""
    msg = str(err)
    if "Sign in to confirm" in msg or "not a bot" in msg:
        return ("유튜브가 로봇인지 확인하려고 막았어요. 크롬·엣지·파이어폭스 중 하나에서 유튜브에 로그인한 뒤 "
                "다시 해 보세요. (파이어폭스가 가장 잘 됩니다)")
    if "Private video" in msg:
        return "비공개 영상이라 받을 수 없어요."
    if _is_age(msg):
        return "연령 제한 영상이에요. 브라우저에서 유튜브에 로그인한 뒤 다시 해 보세요."
    if "Unsupported URL" in msg:
        return "지원하지 않는 주소예요. 영상 페이지 주소를 그대로 복사해서 넣어 주세요."
    if "HTTP Error 404" in msg or "not available" in msg.lower():
        return "영상을 찾을 수 없어요. 삭제됐거나 주소가 잘못됐을 수 있어요."
    if "getaddrinfo" in msg or "connect" in msg.lower():
        return "인터넷 연결을 확인해 주세요."
    return "영상을 받지 못했어요: " + msg.splitlines()[0][:200]


def download(url, job_dir, log):
    import yt_dlp

    log("영상 다운로드 중…")
    opts = {
        "outtmpl": os.path.join(job_dir, "source.%(ext)s"),
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/bv*[height<=1080]+ba/b",
        "merge_output_format": "mp4",
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en", "en-orig", "en.*", "ko", "ja"],
        "subtitlesformat": "json3/vtt/srt/best",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "ignoreerrors": False,
    }

    def attempt(extra):
        with yt_dlp.YoutubeDL({**opts, **extra}) as ydl:
            return ydl.extract_info(url, download=True)

    try:
        info = attempt({})
    except yt_dlp.utils.DownloadError as first:
        msg = str(first)
        if not _needs_login(msg):
            raise JobError(_friendly(first))
        # 브라우저에 로그인된 유튜브 정보를 빌려서 다시 시도
        info = None
        for browser in _BROWSERS:
            try:
                log(f"유튜브 확인 요청 → {browser} 브라우저 로그인 정보로 다시 시도…")
                info = attempt({"cookiesfrombrowser": (browser,)})
                break
            except Exception:
                continue
        if info is None:
            raise JobError(_friendly(first))

    video = next((p for p in glob.glob(os.path.join(job_dir, "source.*"))
                  if p.rsplit(".", 1)[-1] in ("mp4", "mkv", "webm", "mov")), None)
    if not video:
        raise JobError("다운로드한 영상 파일을 찾지 못했습니다.")
    return video, info.get("title", ""), info.get("description", "")


def find_subtitle_file(job_dir):
    files = [p for p in glob.glob(os.path.join(job_dir, "source.*"))
             if p.rsplit(".", 1)[-1] in ("json3", "vtt", "srt")]
    # 사람이 만든 자막(en) > 원어 자동자막(en-orig) > 기타
    def rank(p):
        name = os.path.basename(p)
        if ".en." in name:
            return 0
        if ".en-orig." in name:
            return 1
        if ".ko." in name:
            return 2
        return 3
    files.sort(key=rank)
    return files[0] if files else None


def transcribe(video, log):
    """faster-whisper가 설치되어 있으면 음성 인식."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return []
    log("자막이 없어 음성 인식 중… (faster-whisper)")
    model = WhisperModel("small", compute_type="int8")
    segments, _ = model.transcribe(video, vad_filter=True)
    return [subs.Segment(s.start, s.end, s.text.strip()) for s in segments if s.text.strip()]


# ---------- 2. 렌더 ----------

def video_box(src_w, src_h, layout):
    """영상이 세로 캔버스 안에서 차지할 영역 (x, y, w, h)."""
    max_h = 1200 if layout != "blur" else 1500
    w = W
    h = int(round(src_h * W / src_w / 2) * 2)
    if h > max_h:
        h = max_h
        w = int(round(src_w * max_h / src_h / 2) * 2)
    x = (W - w) // 2
    # 제목 영역(위)과 자막 영역(아래)을 남기고 살짝 위쪽에 배치
    y = int(((H - h) // 2 - 40) / 2) * 2
    y = max(y, 360)
    if y + h > H - 260:
        y = max(0, (H - h) // 2)
    return x, y, w, h


def build_filter(meta, box, layout, mirror, speed, zoom, duration, start):
    x, y, w, h = box
    pre = []
    if zoom and zoom > 1.0:
        pre.append(f"crop=iw/{zoom}:ih/{zoom}")
    if mirror:
        pre.append("hflip")
    pre.append(f"setpts=PTS/{speed}")
    base = ",".join(pre)
    trim = f"trim=start={start},setpts=PTS-STARTPTS," if start else ""

    if layout == "blur":
        bg = (f"[v0]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
              f"boxblur=30:3,eq=brightness=-0.25[bg]")
    else:
        color = "white" if layout == "white" else "black"
        bg = f"color=c={color}:s={W}x{H}:d={duration:.3f}[bg]"
    graph = [
        f"[0:v]{trim}{base},format=yuv420p,split=2[v0][v1]",
        bg,
        f"[v1]scale={w}:{h}:flags=lanczos,setsar=1[fg]",
        f"[bg][fg]overlay={x}:{y}:shortest=1,ass=subs.ass:fontsdir=fonts[out]",
    ]
    if layout != "blur":
        graph[0] = f"[0:v]{trim}{base},format=yuv420p[v1]"
    return ";".join(graph)


def _atempo(speed):
    return f"atempo={speed:.4f}"


def render(job_dir, video, meta, plan_title, highlight_word, segments, channel, font_path, out_path,
           start=0.0, log=print):
    layout = channel["layout"]
    speed = float(channel.get("speed") or 1.0)
    speed = min(max(speed, 0.5), 2.0)
    src_dur = max(meta["duration"] - start, 0.5)
    duration = src_dur / speed
    if channel.get("max_duration"):
        duration = min(duration, float(channel["max_duration"]))
    box = video_box(meta["w"], meta["h"], layout)

    fonts_dir = os.path.join(job_dir, "fonts")
    os.makedirs(fonts_dir, exist_ok=True)
    shutil.copy(font_path, os.path.join(fonts_dir, os.path.basename(font_path)))
    font_name = ImageFont.truetype(font_path, 20).getname()[0]

    timed = subs.retime(segments, offset=start, speed=speed, max_duration=duration)
    ass = subs.build_ass(
        font_name, layout, plan_title, highlight_word, timed, duration,
        title_color=channel["title_color"], highlight_color=channel["highlight_color"],
        subtitle_color=channel["subtitle_color"], watermark=channel.get("watermark", ""),
        video_box=box,
    )
    with open(os.path.join(job_dir, "subs.ass"), "w", encoding="utf-8") as f:
        f.write(ass)

    fg = build_filter(meta, box, layout, channel.get("mirror"), speed,
                      float(channel.get("zoom") or 1.0), duration, start)
    maps = ["-map", "[out]"]
    if meta["has_audio"]:
        a = f"atrim=start={start},asetpts=PTS-STARTPTS," if start else ""
        fg += f";[0:a]{a}{_atempo(speed)}[aout]"
        maps += ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", os.path.abspath(video),
           "-filter_complex", fg] + maps
    cmd += ["-t", f"{duration:.3f}", "-r", "30", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", os.path.abspath(out_path)]
    log("영상 렌더링 중… (FFmpeg)")
    _run(cmd, cwd=job_dir)
    return duration


# ---------- 전체 실행 ----------

def safe_name(text, limit=40):
    text = re.sub(r'[\\/:*?"<>|\n\r\t]', "", text).strip()
    return (text[:limit] or "shorts").strip()


def run_job(job, settings, channel, log):
    """job: dict(id, url | file, title_override, start)."""
    job_dir = os.path.join(WORK_DIR, job["id"])
    os.makedirs(job_dir, exist_ok=True)

    font_path = find_font(settings)
    if not font_path:
        raise JobError("한글 폰트를 찾지 못했습니다. 설정에서 폰트 파일(.ttf/.otf) 경로를 지정하세요.")

    # 1) 소스
    if job.get("file"):
        video, src_title, src_desc = job["file"], os.path.splitext(os.path.basename(job["file"]))[0], ""
    else:
        video, src_title, src_desc = download(job["url"], job_dir, log)
    meta = probe(video)
    log(f"원본: {meta['w']}x{meta['h']}, {meta['duration']:.1f}초")

    # 2) 자막
    segments = []
    sub_file = find_subtitle_file(job_dir)
    if sub_file:
        segments = subs.parse_file(sub_file)
        log(f"원본 자막 {len(segments)}줄 확보 ({os.path.basename(sub_file)})")
    if not segments:
        segments = transcribe(video, log)

    # 3) AI 각색
    api_key = settings.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
    title_lines = [x for x in (job.get("title_override") or "").split("/") if x.strip()]
    hl = job.get("highlight") or ""
    plan = None
    if api_key:
        log("AI가 제목과 자막을 각색하는 중… (Claude)")
        from ai import make_plan
        plan = make_plan(api_key, settings.get("model") or "claude-opus-5-5", channel["tone"],
                         src_title, src_desc, segments, translate=channel.get("translate", True))
        if not title_lines:
            title_lines = [plan.title_line1, plan.title_line2]
            hl = hl or plan.highlight_word
        if channel.get("translate", True) and plan.subtitles:
            by_i = {s.i: s.text for s in plan.subtitles}
            segments = [subs.Segment(s.start, s.end, by_i.get(i, s.text)) for i, s in enumerate(segments)]
    else:
        log("API 키가 없어 AI 각색은 건너뜁니다 (원본 자막/직접 입력 제목 사용).")
    if not title_lines:
        title_lines = subs.wrap_korean(src_title, 14)[:2]

    # 4) 렌더
    out_dir = os.path.join(OUTPUT_DIR, safe_name(channel["name"], 30))
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"{stamp}_{safe_name(' '.join(title_lines))}"
    out_path = os.path.join(out_dir, base + ".mp4")
    duration = render(job_dir, video, meta, title_lines, hl, segments, channel, font_path, out_path,
                      start=float(job.get("start") or 0), log=log)

    # 5) 업로드용 메타데이터
    with open(os.path.join(out_dir, base + ".txt"), "w", encoding="utf-8") as f:
        if plan:
            f.write(f"제목: {plan.upload_title}\n\n{plan.description}\n\n")
            f.write(" ".join("#" + t.lstrip("#") for t in plan.hashtags) + " #shorts\n")
        else:
            f.write(f"제목: {' '.join(title_lines)}\n")
        f.write(f"\n원본: {job.get('url') or job.get('file')}\n")

    if not job.get("keep_work"):
        shutil.rmtree(job_dir, ignore_errors=True)
    return {"output": out_path, "duration": round(duration, 1), "title": title_lines}
