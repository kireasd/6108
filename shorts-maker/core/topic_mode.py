"""🅰 주제만 넣으면 쇼츠 완성."""
import os
import random
import re
import shutil
import time

from . import captions, config, llm, tts, video, visuals

SYSTEM = (
    "너는 유튜브 쇼츠 대본 작가야. 시청자가 끝까지 보게 만드는 짧고 재밌는 한국어 대본을 쓴다. "
    "반드시 JSON으로만 답한다."
)

PROMPT = """주제: {topic}

이 주제로 {seconds}초 정도 길이의 유튜브 쇼츠 대본을 써줘.
규칙:
- 첫 문장은 시청자의 호기심을 확 끄는 질문이나 놀라운 사실로 시작
- 장면은 {scenes}개, 장면마다 한국어 한두 문장 (말로 읽기 좋게, 짧게)
- 마지막 장면은 여운이 남게 마무리
- 각 장면마다 배경 영상 검색용 영어 키워드(1~3단어)를 붙여
- title은 화면 위에 띄울 15자 이내 한국어 제목

JSON 형식:
{{"title": "제목", "scenes": [{{"text": "나레이션 문장", "keyword": "english keyword"}}]}}"""


def write_script(topic, settings, seconds=45):
    """대본을 AI로 만든다. (제목, [문장], [영어키워드])"""
    scenes = max(4, round(seconds / 7))
    data = llm.ask_json(settings, PROMPT.format(topic=topic, seconds=seconds, scenes=scenes), SYSTEM)
    items = [s for s in data.get("scenes", []) if str(s.get("text", "")).strip()]
    if not items:
        raise llm.LLMError("AI가 대본을 비워서 보냈어요. 한 번 더 시도해 주세요.")
    title = str(data.get("title", topic)).strip()[:30]
    lines = [str(s["text"]).strip() for s in items]
    keywords = [str(s.get("keyword", "")).strip() for s in items]
    return title, lines, keywords


def safe_name(text):
    return re.sub(r'[\\/:*?"<>|\n]', "", text).strip()[:40] or "쇼츠"


def pick_bgm():
    folder = os.path.join(config.APP_DIR, "bgm")
    if not os.path.isdir(folder):
        return None
    songs = [os.path.join(folder, f) for f in os.listdir(folder)
             if f.lower().endswith((".mp3", ".wav", ".m4a", ".ogg"))]
    return random.choice(songs) if songs else None


def make_video(title, lines, keywords, settings, progress=lambda f, d: None):
    """대본으로 영상 파일을 만들고 경로를 돌려준다."""
    lines = [l.strip() for l in lines if l.strip()]
    if not lines:
        raise ValueError("대본이 비어 있어요.")
    stamp = time.strftime("%Y%m%d_%H%M%S")
    work = config.new_work_dir("topic_" + stamp)
    title_png = captions.render(title, os.path.join(work, "title.png"), size=88,
                                color=(255, 230, 80)) if title.strip() else None

    used, parts = set(), []
    last_keyword = keywords[0] if keywords else ""
    for i, text in enumerate(lines):
        step = f"장면 {i + 1}/{len(lines)}"
        keyword = keywords[i] if i < len(keywords) and keywords[i] else last_keyword
        last_keyword = keyword

        progress(i / (len(lines) + 1), f"{step}: 목소리 만드는 중")
        audio = tts.speak(text, os.path.join(work, f"voice_{i}.mp3"), settings)

        progress((i + 0.4) / (len(lines) + 1), f"{step}: 배경 영상 찾는 중")
        bg = visuals.find_video(keyword, os.path.join(work, f"bg_{i}.mp4"), settings, used)

        progress((i + 0.7) / (len(lines) + 1), f"{step}: 장면 합치는 중")
        cap = captions.render(text, os.path.join(work, f"cap_{i}.png"))
        parts.append(video.make_scene(audio, cap, os.path.join(work, f"scene_{i}.mp4"),
                                      background=bg, title_png=title_png, index=i))

    progress(len(lines) / (len(lines) + 1), "마지막으로 이어 붙이는 중")
    name = f"{stamp}_{safe_name(title)}"
    out = os.path.join(config.output_dir(settings), name + ".mp4")
    video.concat(parts, out, bgm=pick_bgm(), work_dir=work)
    with open(os.path.join(config.output_dir(settings), name + ".txt"), "w", encoding="utf-8") as f:
        f.write(title + "\n\n" + "\n".join(lines) + "\n")
    shutil.rmtree(work, ignore_errors=True)  # 중간 파일 정리
    progress(1, "완성!")
    return out
