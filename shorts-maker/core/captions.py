"""자막 그림(PNG) 만들기. 투명 배경에 테두리 있는 큰 글씨."""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

WIDTH = 1080
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\malgunbd.ttf",
    r"C:\Windows\Fonts\malgun.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
]


def _font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    if sys.platform != "win32":
        return ImageFont.load_default(size)
    raise FileNotFoundError("한글 글꼴(맑은 고딕)을 찾지 못했어요.")


def _wrap(draw, text, font, max_width):
    """글자 단위로 줄바꿈 (한글은 띄어쓰기가 적어도 잘 맞도록)."""
    lines, line = [], ""
    for word in text.split(" "):
        candidate = (line + " " + word).strip()
        if draw.textlength(candidate, font=font) <= max_width:
            line = candidate
            continue
        if line:
            lines.append(line)
        line = ""
        for ch in word:
            if draw.textlength(line + ch, font=font) > max_width and line:
                lines.append(line)
                line = ""
            line += ch
    if line:
        lines.append(line)
    return lines


def render(text, out_path, size=78, color=(255, 255, 255)):
    """자막 PNG를 만들고 경로를 돌려준다. 높이는 글 길이에 맞춘다."""
    font = _font(size)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lines = _wrap(probe, text, font, WIDTH - 140)
    line_h = int(size * 1.3)
    stroke = max(4, size // 12)
    height = line_h * len(lines) + stroke * 4
    img = Image.new("RGBA", (WIDTH, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    y = stroke * 2
    for line in lines:
        w = draw.textlength(line, font=font)
        draw.text(((WIDTH - w) / 2, y), line, font=font, fill=color,
                  stroke_width=stroke, stroke_fill=(0, 0, 0))
        y += line_h
    img.save(out_path)
    return out_path
