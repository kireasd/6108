"""쇼츠 자동 제작기 - 프로그램 창(pywebview)으로 여는 데스크톱 프로그램.

화면은 ui/ 폴더의 HTML로 그리고, 실제 작업은 core/ 의 파이썬 코드가 한다.
화면(자바스크립트)은 pywebview.api.함수이름() 으로 아래 Api 클래스를 부른다.
"""
import json
import os
import subprocess
import sys
import threading
import time
import traceback
import webbrowser

import webview

from core import clip_mode, config, llm, source_finder, topic_mode, tts, visuals

VERSION = "0.5.0"
UI_FILE = os.path.join(config.APP_DIR, "ui", "index.html")
LOG_FILE = os.path.join(config.APP_DIR, "app.log")
JOB_NAMES = {"find": "원본 찾기", "verify": "정밀 확인", "download": "원본 받기", "script": "대본 만들기",
             "topic": "영상 만들기", "clips": "긴 영상 자르기"}
VIDEO_TYPES = ("영상 파일 (*.mp4;*.mov;*.mkv;*.avi;*.webm;*.m4v)", "모든 파일 (*.*)")


def log_error(text):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + text + "\n")


def open_in_system(path):
    if sys.platform == "win32":
        os.startfile(path)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])


def copy_image(path):
    """사진을 윈도우 클립보드에 복사한다 (붙여넣기 Ctrl+V 용)."""
    if sys.platform != "win32" or not os.path.exists(path):
        return False
    safe = path.replace("'", "''")
    script = ("Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; "
              f"[System.Windows.Forms.Clipboard]::SetImage([System.Drawing.Image]::FromFile('{safe}'))")
    proc = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", script],
                          capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    return proc.returncode == 0


class Api:
    # pywebview는 js_api의 공개 속성까지 화면에 연결하려 하므로 내부 값은 밑줄(_)로 숨긴다
    def __init__(self):
        self._settings = config.load_settings()
        self._window = None
        self._busy = None  # 지금 하고 있는 작업 이름
        self._cancel = threading.Event()

    # ---------- 화면에 보여줄 정보 ----------
    def get_state(self):
        ok, msg = llm.check(self._settings)
        return {
            "version": VERSION,
            "settings": self._settings,
            "providers": llm.PROVIDERS,
            "voices": tts.VOICES,
            "ai": {"ok": ok, "msg": msg},
            "pexels": visuals.has_key(self._settings),
            "busy": self._busy,
        }

    def set_provider(self, key):
        if key in llm.PROVIDERS:
            self._settings["provider"] = key
            config.save_settings(self._settings)
        return self.get_state()

    def save_settings(self, data):
        allowed = set(config.DEFAULTS)
        for k, v in (data or {}).items():
            if k in allowed:
                self._settings[k] = v.strip() if isinstance(v, str) else v
        for k, v in config.DEFAULTS.items():
            if self._settings.get(k) in ("", None):
                self._settings[k] = v if not k.endswith("_key") else ""
        config.save_settings(self._settings)
        return self.get_state()

    def list_library(self):
        """완성 영상 폴더(와 그 안의 '원본' 폴더)의 영상 목록, 최신순."""
        root = config.output_dir(self._settings)
        items = []
        for folder, kind in ((root, "쇼츠"), (os.path.join(root, "원본"), "원본")):
            if not os.path.isdir(folder):
                continue
            for name in os.listdir(folder):
                if name.lower().endswith(".mp4"):
                    path = os.path.join(folder, name)
                    st = os.stat(path)
                    items.append({"name": name, "path": path, "kind": kind,
                                  "size": round(st.st_size / 1024 / 1024, 1),
                                  "date": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
                                  "mtime": st.st_mtime})
        items.sort(key=lambda x: x["mtime"], reverse=True)
        return items

    # ---------- 파일·폴더 열기 ----------
    def pick_video(self):
        result = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=VIDEO_TYPES)
        return result[0] if result else None

    def pick_folder(self):
        result = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        return result[0] if result else None

    def open_path(self, path):
        if path and os.path.exists(path):
            open_in_system(path)
            return True
        return False

    def open_folder_of(self, path):
        if sys.platform == "win32" and path and os.path.exists(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            return True
        return self.open_path(os.path.dirname(path))

    def open_output(self):
        return self.open_path(config.output_dir(self._settings))

    def open_url(self, url):
        if url.startswith(("https://", "http://")):
            webbrowser.open(url)

    def image_search(self, path, engine):
        """장면 사진을 복사해 두고 이미지 검색 사이트를 연다. 사이트에서 Ctrl+V만 누르면 된다."""
        sites = {"google": "https://www.google.com/imghp", "bing": "https://www.bing.com/images"}
        copied = copy_image(path)
        webbrowser.open(sites.get(engine, sites["google"]))
        return copied

    # ---------- 오래 걸리는 작업 ----------
    def start_job(self, kind, params):
        """작업을 뒤에서 돌리고 바로 돌아온다. 진행 상황은 window.onJob(...)으로 알려준다."""
        if self._busy:
            return {"ok": False, "msg": f"'{JOB_NAMES.get(self._busy, self._busy)}' 작업이 아직 진행 중이에요. 끝난 뒤에 다시 눌러 주세요."}
        job = getattr(self, "_job_" + kind, None)
        if not job:
            return {"ok": False, "msg": "알 수 없는 작업이에요."}
        self._busy = kind
        threading.Thread(target=self._run, args=(kind, job, params or {}), daemon=True).start()
        return {"ok": True}

    def cancel(self):
        """'그만하기' 버튼. 지금 하는 작업이 다음 확인 지점에서 멈춘다."""
        if self._busy:
            self._cancel.set()
        return bool(self._busy)

    def _send(self, payload):
        if self._window:
            self._window.evaluate_js(f"window.onJob({json.dumps(payload, ensure_ascii=False)})")

    def _run(self, kind, job, params):
        last = [0.0]
        self._cancel.clear()

        def progress(frac, msg):
            if self._cancel.is_set():
                raise config.Cancelled()
            if frac is None:  # 그만하기 확인만 하는 신호
                return
            now = time.time()
            if now - last[0] > 0.15 or frac >= 1:  # 화면에 너무 자주 보내지 않기
                last[0] = now
                self._send({"type": "progress", "kind": kind, "frac": frac, "msg": msg})

        try:
            result = job(params, progress)
            self._send({"type": "done", "kind": kind, "result": result})
        except config.Cancelled:
            self._send({"type": "cancelled", "kind": kind})
        except Exception as e:
            if self._cancel.is_set():
                self._send({"type": "cancelled", "kind": kind})
            else:
                log_error(f"{kind} 실패\n{traceback.format_exc()}")
                self._send({"type": "error", "kind": kind, "msg": str(e) or e.__class__.__name__})
        finally:
            self._busy = None

    def _job_find(self, p, progress):
        return source_finder.find(p["source"], self._settings, progress,
                                  use_speech=p.get("speech", True), auto_deep=p.get("deep", False))

    def _job_verify(self, p, progress):
        return source_finder.verify(p["id"], progress)

    def _job_download(self, p, progress):
        return {"path": source_finder.download_original(p["url"], self._settings, progress),
                "then": p.get("then")}

    def _job_script(self, p, progress):
        progress(0.2, "AI가 대본 쓰는 중... (10초~1분)")
        title, lines, keywords = topic_mode.write_script(p["topic"], self._settings, int(p.get("seconds", 45)))
        progress(1, "대본 완성!")
        return {"title": title, "lines": lines, "keywords": keywords}

    def _job_topic(self, p, progress):
        return {"path": topic_mode.make_video(p["title"], p["lines"], p.get("keywords") or [],
                                              self._settings, progress)}

    def _job_clips(self, p, progress):
        paths, notes = clip_mode.make_shorts(p["path"], self._settings, int(p.get("count", 3)), progress)
        return {"paths": paths, "notes": notes}


def main():
    api = Api()
    api._window = webview.create_window(
        f"쇼츠 자동 제작기 {VERSION}", UI_FILE, js_api=api,
        width=1280, height=860, min_size=(1000, 700), background_color="#F4F5F7",
    )
    webview.start(debug="--debug" in sys.argv)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log_error("프로그램 시작 실패\n" + traceback.format_exc())
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0, f"프로그램을 켜지 못했어요.\n\n{LOG_FILE} 파일 내용을 보내 주세요.", "쇼츠 자동 제작기", 0x10)
        raise
