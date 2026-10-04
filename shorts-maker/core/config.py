"""설정 저장/불러오기와 공통 경로."""
import json
import os
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")
WORK_DIR = os.path.join(APP_DIR, "work")


def desktop_dir():
    """바탕화면 경로. OneDrive로 옮겨진 바탕화면도 찾는다."""
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            )
            value, _ = winreg.QueryValueEx(key, "Desktop")
            path = os.path.expandvars(value)
            if os.path.isdir(path):
                return path
        except OSError:
            pass
    return os.path.join(os.path.expanduser("~"), "Desktop")


DEFAULTS = {
    "output_dir": os.path.join(desktop_dir(), "쇼츠"),
    "provider": "local",
    "ollama_url": "http://localhost:11434",
    "ollama_model": "gemma3:12b",
    "claude_key": "",
    "claude_model": "claude-opus-5-5",
    "openai_key": "",
    "openai_model": "gpt-5-mini",
    "gemini_key": "",
    "gemini_model": "gemini-2.5-flash",
    "voice": "ko-KR-SunHiNeural",
    "voice_rate": "+10%",
    "pexels_key": "",
    "vision_key": "",
    "whisper_model": "large-v3-turbo",
}


def load_settings():
    settings = dict(DEFAULTS)
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                settings.update(json.load(f))
        except (OSError, ValueError):
            pass
    return settings


def save_settings(settings):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def output_dir(settings):
    path = settings.get("output_dir") or DEFAULTS["output_dir"]
    os.makedirs(path, exist_ok=True)
    return path


def new_work_dir(name):
    path = os.path.join(WORK_DIR, name)
    os.makedirs(path, exist_ok=True)
    return path
