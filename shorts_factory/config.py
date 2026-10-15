"""설정 / 채널 프리셋 저장소 (JSON 파일 기반)."""
import json
import os
import sys
import threading

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")
WORK_DIR = os.path.join(BASE_DIR, "work")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

DEFAULT_CHANNEL = {
    "id": "default",
    "name": "기본 채널",
    "layout": "black",          # black | white | blur
    "title_color": "#FFFFFF",
    "highlight_color": "#FFD400",
    "subtitle_color": "#FFFFFF",
    "watermark": "",            # 영상 하단에 표시할 채널명 (비우면 표시 안 함)
    "tone": "호기심을 자극하는 짧고 강한 한국어 쇼츠 말투",
    "mirror": True,             # 좌우 반전
    "speed": 1.05,              # 재생 속도
    "zoom": 1.05,               # 확대 비율 (테두리 크롭)
    "max_duration": 59,         # 최대 길이(초), 0 = 제한 없음
    "translate": True,          # 자막을 한국어로 번역
}

DEFAULT_SETTINGS = {
    "anthropic_api_key": "",
    "model": "claude-opus-5-5",
    "font_file": "",            # 비우면 자동 탐색 (맑은고딕/나눔고딕/Noto)
    "channels": [DEFAULT_CHANNEL],
}

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\malgunbd.ttf",
    r"C:\Windows\Fonts\malgun.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothicExtraBold.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
]

_lock = threading.Lock()


def load_settings():
    with _lock:
        data = {}
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError):
                data = {}
    merged = {**DEFAULT_SETTINGS, **data}
    merged["channels"] = [{**DEFAULT_CHANNEL, **c} for c in (merged.get("channels") or [DEFAULT_CHANNEL])]
    return merged


def save_settings(settings):
    with _lock:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)


def get_channel(settings, channel_id):
    for c in settings["channels"]:
        if c["id"] == channel_id:
            return c
    return settings["channels"][0]


def find_font(settings):
    path = settings.get("font_file") or ""
    if path and os.path.exists(path):
        return path
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    return None
