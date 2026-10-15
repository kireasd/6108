"""자막 파싱(json3 / vtt / srt) 및 ASS(제목+자막) 생성."""
import json
import re
from dataclasses import dataclass


@dataclass
class Segment:
    start: float
    end: float
    text: str


# ---------- 파싱 ----------

def parse_json3(raw):
    data = json.loads(raw)
    segs = []
    for ev in data.get("events", []):
        if "segs" not in ev:
            continue
        text = "".join(s.get("utf8", "") for s in ev["segs"]).replace("\n", " ").strip()
        if not text:
            continue
        start = ev.get("tStartMs", 0) / 1000
        end = start + ev.get("dDurationMs", 2000) / 1000
        segs.append(Segment(start, end, text))
    return _fix_overlaps(segs)


_TS = r"(\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{3}"


def _to_sec(ts):
    ts = ts.replace(",", ".")
    parts = ts.split(":")
    parts = [float(p) for p in parts]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def parse_vtt_or_srt(raw):
    """VTT/SRT 공용 파서. 유튜브 자동자막의 '굴러가는' 중복 줄을 제거한다."""
    segs = []
    blocks = re.split(r"\n\s*\n", raw.replace("\r", ""))
    for b in blocks:
        m = re.search(rf"({_TS})\s*-->\s*({_TS})", b)
        if not m:
            continue
        start, end = _to_sec(m.group(1)), _to_sec(m.group(3))
        body = b[m.end():].split("\n")
        lines = []
        for ln in body:
            ln = re.sub(r"<[^>]+>", "", ln).strip()
            if ln and not re.fullmatch(r"align:.*|position:.*", ln):
                lines.append(ln)
        if not lines:
            continue
        # 자동자막은 직전 줄을 반복하므로 마지막 줄만 새 내용
        text = lines[-1] if len(lines) > 1 else lines[0]
        if segs and segs[-1].text == text:
            segs[-1].end = end
            continue
        segs.append(Segment(start, end, text))
    return _fix_overlaps(segs)


def _fix_overlaps(segs):
    segs = [s for s in segs if s.end > s.start]
    segs.sort(key=lambda s: s.start)
    for a, b in zip(segs, segs[1:]):
        if a.end > b.start:
            a.end = b.start
    return [s for s in segs if s.end - s.start > 0.05]


def parse_file(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        raw = f.read()
    if path.endswith(".json3"):
        return parse_json3(raw)
    return parse_vtt_or_srt(raw)


def retime(segs, offset=0.0, speed=1.0, max_duration=0):
    """구간 잘라내기(offset) + 배속 반영 + 최대 길이 제한."""
    out = []
    for s in segs:
        st, en = (s.start - offset) / speed, (s.end - offset) / speed
        if en <= 0:
            continue
        st = max(st, 0)
        if max_duration and st >= max_duration:
            break
        if max_duration:
            en = min(en, max_duration)
        out.append(Segment(st, en, s.text))
    return out


# ---------- ASS 생성 ----------

def _ass_color(hex_color):
    h = hex_color.lstrip("#")
    if len(h) != 6:
        h = "FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}".upper()


def _ass_time(t):
    t = max(t, 0)
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _escape(text):
    return text.replace("\\", "＼").replace("{", "(").replace("}", ")").replace("\n", " ")


def wrap_korean(text, width=16):
    """자막을 한 줄 최대 width 글자 정도로 2줄까지 나눈다."""
    text = text.strip()
    if len(text) <= width:
        return [text]
    words = text.split(" ")
    lines, cur = [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    if len(lines) > 2:
        mid = (len(words) + 1) // 2
        lines = [" ".join(words[:mid]), " ".join(words[mid:])]
    return lines


def highlight(text, word, color):
    """제목의 강조 단어에 색을 입힌다."""
    safe = _escape(text)
    if word and word in text:
        w = _escape(word)
        return safe.replace(w, "{\\c" + _ass_color(color) + "&}" + w + "{\\r}", 1)
    return safe


def build_ass(font_name, layout, title_lines, highlight_word, segments, duration,
              title_color="#FFFFFF", highlight_color="#FFD400", subtitle_color="#FFFFFF",
              watermark="", video_box=(0, 656, 1080, 608)):
    """1080x1920 캔버스용 ASS. video_box = (x, y, w, h) 영상이 놓인 위치."""
    dark_text = layout == "white"
    tcol = "#111111" if dark_text and title_color.upper() == "#FFFFFF" else title_color
    scol = "#111111" if dark_text and subtitle_color.upper() == "#FFFFFF" else subtitle_color
    outline = "&H00FFFFFF" if dark_text else "&H00000000"
    mark_outline = 0 if dark_text else 2
    _, vy, _, vh = video_box
    title_bottom = vy - 40
    sub_y = vy + vh + 70

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Title,{font_name},92,{_ass_color(tcol)},&H000000FF,{outline},&H64000000,-1,0,0,0,100,100,0,0,1,5,0,2,60,60,0,1
Style: Sub,{font_name},70,{_ass_color(scol)},&H000000FF,{outline},&H96000000,-1,0,0,0,100,100,0,0,1,6,2,8,70,70,0,1
Style: Mark,{font_name},40,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,{mark_outline},0,2,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    end = _ass_time(duration)
    events = []
    title = "\\N".join(highlight(line, highlight_word, highlight_color) for line in title_lines if line)
    if title:
        events.append(f"Dialogue: 1,0:00:00.00,{end},Title,,0,0,0,,{{\\pos(540,{title_bottom})}}{title}")
    for s in segments:
        body = "\\N".join(_escape(x) for x in wrap_korean(s.text))
        events.append(f"Dialogue: 0,{_ass_time(s.start)},{_ass_time(s.end)},Sub,,0,0,0,,{{\\pos(540,{sub_y})}}{body}")
    if watermark:
        mark_col = "&H00333333" if dark_text else "&H00FFFFFF"
        events.append(f"Dialogue: 0,0:00:00.00,{end},Mark,,0,0,0,,{{\\pos(540,1840)\\c{mark_col}&\\alpha&H40&}}{_escape(watermark)}")
    return header + "\n".join(events) + "\n"
