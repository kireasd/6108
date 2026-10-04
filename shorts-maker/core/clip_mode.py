"""🅱 긴 영상에서 재밌는 부분을 골라 쇼츠로 자르기."""
import glob
import os
import shutil
import sys
import time

from . import captions, config, llm, video
from .topic_mode import safe_name

SYSTEM = "너는 유튜브 쇼츠 편집자야. 긴 영상에서 쇼츠로 만들면 조회수가 잘 나올 구간을 고른다. 반드시 JSON으로만 답한다."

PROMPT = """아래는 영상의 대사 기록이야. [시작초-끝초] 대사 형식이야.

{transcript}

여기서 쇼츠로 만들기 좋은 구간 {count}개를 골라줘.
규칙:
- 구간 길이는 {min_len}~{max_len}초
- 혼자 봐도 이해되고, 재밌거나 놀랍거나 감동적인 부분
- 구간끼리 겹치지 않게
- title은 화면 위에 띄울 15자 이내 한국어 제목

JSON 형식:
{{"clips": [{{"start": 시작초, "end": 끝초, "title": "제목", "reason": "고른 이유 한 줄"}}]}}"""

_whisper = None


def _add_cuda_dlls():
    """pip로 설치한 NVIDIA 라이브러리를 윈도우가 찾을 수 있게 한다."""
    if sys.platform != "win32":
        return
    for path in glob.glob(os.path.join(sys.prefix, "Lib", "site-packages", "nvidia", "*", "bin")):
        os.add_dll_directory(path)
        os.environ["PATH"] = path + os.pathsep + os.environ["PATH"]


def _load_whisper(settings):
    global _whisper
    if _whisper is None:
        _add_cuda_dlls()
        from faster_whisper import WhisperModel
        try:
            _whisper = WhisperModel(settings["whisper_model"], device="cuda", compute_type="float16")
        except Exception:
            # 그래픽카드를 못 쓰면 CPU로 (느리지만 동작함)
            _whisper = WhisperModel(settings["whisper_model"], device="cpu", compute_type="int8")
    return _whisper


def transcribe(src, settings, progress=lambda f, d: None, out=None, fast=False):
    """영상 속 말을 글자로. [(시작초, 끝초, 문장)]

    out: 목록을 주면 알아들은 문장을 하나씩 바로 넣는다 (시간제한으로 중간에 그만둘 때 쓰려고).
    fast: 원본 찾기용. 정확도보다 속도를 우선한다.
    """
    progress(0.02, "음성 인식 AI 불러오는 중 (처음 한 번은 내려받느라 5~15분 걸려요)")
    model = _load_whisper(settings)
    total = video.duration(src)
    segments, _ = model.transcribe(
        src, language="ko", vad_filter=True,
        # 노래·음악 부분에서 같은 곳을 계속 다시 듣느라 멈춘 것처럼 되는 것을 막는다
        condition_on_previous_text=False,
        temperature=0.0 if fast else [0.0, 0.2, 0.4],
        beam_size=1 if fast else 5,
    )
    result = out if out is not None else []
    for seg in segments:
        result.append((seg.start, seg.end, seg.text.strip()))
        progress(0.05 + 0.5 * min(seg.end / total, 1), f"말 알아듣는 중... {int(seg.end)}/{int(total)}초")
    return result


def pick_clips(segments, settings, count=3, min_len=20, max_len=59):
    lines = "\n".join(f"[{s:.0f}-{e:.0f}] {t}" for s, e, t in segments)
    if len(lines) > 24000:  # 너무 길면 AI가 못 읽으니 앞부분만
        lines = lines[:24000]
    data = llm.ask_json(settings, PROMPT.format(transcript=lines, count=count,
                                                min_len=min_len, max_len=max_len), SYSTEM)
    clips = []
    end_of_video = segments[-1][1] if segments else 0
    for c in data.get("clips", []):
        try:
            start, end = float(c["start"]), float(c["end"])
        except (KeyError, TypeError, ValueError):
            continue
        end = min(end, start + max_len, end_of_video)
        if end - start >= 5:
            clips.append({"start": start, "end": end,
                          "title": str(c.get("title", "")).strip()[:30],
                          "reason": str(c.get("reason", "")).strip()})
    if not clips:
        raise llm.LLMError("AI가 쓸 만한 구간을 못 찾았어요. 한 번 더 시도해 주세요.")
    return clips


def _clip_captions(segments, start, end, work, prefix):
    caps = []
    for i, (s, e, text) in enumerate(segments):
        if e <= start or s >= end or not text:
            continue
        png = captions.render(text, os.path.join(work, f"{prefix}_cap_{i}.png"), size=70)
        caps.append((max(s, start) - start, min(e, end) - start, png))
    return caps


def make_shorts(src, settings, count=3, progress=lambda f, d: None):
    """긴 영상 → 쇼츠 여러 개. 만든 파일 경로 목록과 설명을 돌려준다."""
    stamp = time.strftime("%Y%m%d_%H%M%S")
    work = config.new_work_dir("clip_" + stamp)
    segments = transcribe(src, settings, progress)
    if not segments:
        raise ValueError("영상에서 말소리를 찾지 못했어요.")

    progress(0.6, "AI가 재밌는 부분 고르는 중")
    clips = pick_clips(segments, settings, count)

    outputs, notes = [], []
    for n, clip in enumerate(clips, 1):
        progress(0.6 + 0.4 * (n - 1) / len(clips), f"쇼츠 {n}/{len(clips)} 자르는 중")
        title_png = None
        if clip["title"]:
            title_png = captions.render(clip["title"], os.path.join(work, f"c{n}_title.png"),
                                        size=88, color=(255, 230, 80))
        caps = _clip_captions(segments, clip["start"], clip["end"], work, f"c{n}")
        name = f"{stamp}_{n}_{safe_name(clip['title'] or '쇼츠')}.mp4"
        out = os.path.join(config.output_dir(settings), name)
        video.cut_vertical(src, clip["start"], clip["end"], caps, out, title_png)
        outputs.append(out)
        notes.append(f"{n}. {clip['title']} ({clip['start']:.0f}초~{clip['end']:.0f}초) - {clip['reason']}")
    shutil.rmtree(work, ignore_errors=True)  # 중간 파일 정리
    progress(1, "완성!")
    return outputs, "\n".join(notes)
