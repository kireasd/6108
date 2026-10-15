"""딸깍 쇼츠 공장 - 로컬 웹 앱 (http://127.0.0.1:5077)."""
import os
import queue
import socket
import sys
import threading
import time
import traceback
import uuid
import webbrowser

from flask import Flask, jsonify, request, send_file, render_template
from werkzeug.utils import secure_filename

import config
from pipeline import run_job

app = Flask(__name__, template_folder=os.path.join(config.RES_DIR, "templates"),
            static_folder=os.path.join(config.RES_DIR, "static"))
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024

jobs = {}            # id -> job dict (상태 표시용)
job_queue = queue.Queue()
jobs_lock = threading.Lock()


def _public(job):
    keys = ("id", "source", "channel", "status", "logs", "result", "error", "created")
    return {k: job.get(k) for k in keys}


def worker():
    while True:
        job_id = job_queue.get()
        job = jobs.get(job_id)
        if not job or job["status"] == "canceled":
            continue
        job["status"] = "running"

        def log(msg, job=job):
            job["logs"].append(f"[{time.strftime('%H:%M:%S')}] {msg}")

        try:
            settings = config.load_settings()
            channel = config.get_channel(settings, job["channel_id"])
            job["result"] = run_job(job, settings, channel, log)
            job["status"] = "done"
            if job.get("file") and os.path.dirname(job["file"]).endswith("uploads"):
                try:
                    os.remove(job["file"])
                except OSError:
                    pass
            log("완료!")
        except Exception as e:  # 작업 하나가 실패해도 큐는 계속 돈다
            job["status"] = "error"
            job["error"] = str(e)
            log("오류: " + str(e))
            traceback.print_exc()


def _add_job(source, channel_id, **extra):
    settings = config.load_settings()
    ch = config.get_channel(settings, channel_id)
    job = {
        "id": time.strftime("%m%d%H%M%S") + "_" + uuid.uuid4().hex[:6],
        "source": source,
        "channel_id": ch["id"],
        "channel": ch["name"],
        "status": "queued",
        "logs": [],
        "result": None,
        "error": None,
        "created": time.time(),
        **extra,
    }
    with jobs_lock:
        jobs[job["id"]] = job
    job_queue.put(job["id"])
    return job


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/settings")
def get_settings():
    s = config.load_settings()
    key = s.get("anthropic_api_key") or ""
    s["anthropic_api_key"] = ""
    s["has_api_key"] = bool(key or os.environ.get("ANTHROPIC_API_KEY"))
    s["detected_font"] = config.find_font(s) or ""
    return jsonify(s)


@app.post("/api/settings")
def post_settings():
    body = request.get_json(force=True)
    s = config.load_settings()
    if body.get("anthropic_api_key"):
        s["anthropic_api_key"] = body["anthropic_api_key"].strip()
    if body.get("clear_api_key"):
        s["anthropic_api_key"] = ""
    for k in ("model", "font_file"):
        if k in body:
            s[k] = (body[k] or "").strip()
    if "channels" in body:
        chans = []
        for c in body["channels"]:
            c = {**config.DEFAULT_CHANNEL, **c}
            c["id"] = c.get("id") or uuid.uuid4().hex[:8]
            c["speed"] = float(c["speed"])
            c["zoom"] = float(c["zoom"])
            c["max_duration"] = int(c["max_duration"])
            chans.append(c)
        s["channels"] = chans or [config.DEFAULT_CHANNEL]
    config.save_settings(s)
    return jsonify({"ok": True})


@app.post("/api/jobs")
def create_jobs():
    """URL 여러 개(줄바꿈) 또는 파일 업로드로 작업 등록."""
    channel_id = request.form.get("channel_id", "")
    title = request.form.get("title", "").strip()
    highlight = request.form.get("highlight", "").strip()
    start = request.form.get("start", "0") or "0"
    created = []
    for line in request.form.get("urls", "").splitlines():
        url = line.strip()
        if url.startswith("http"):
            created.append(_add_job(url, channel_id, url=url, title_override=title,
                                    highlight=highlight, start=start))
    for f in request.files.getlist("files"):
        if not f.filename:
            continue
        up_dir = os.path.join(config.WORK_DIR, "uploads")
        os.makedirs(up_dir, exist_ok=True)
        name = f"{uuid.uuid4().hex[:6]}_{secure_filename(f.filename) or 'video.mp4'}"
        path = os.path.join(up_dir, name)
        f.save(path)
        created.append(_add_job(f.filename, channel_id, file=path, title_override=title,
                                highlight=highlight, start=start))
    if not created:
        return jsonify({"error": "URL 또는 영상 파일을 넣어주세요."}), 400
    return jsonify({"jobs": [_public(j) for j in created]})


@app.get("/api/jobs")
def list_jobs():
    with jobs_lock:
        items = sorted(jobs.values(), key=lambda j: j["created"], reverse=True)
    return jsonify([_public(j) for j in items])


@app.delete("/api/jobs/<job_id>")
def delete_job(job_id):
    job = jobs.get(job_id)
    if job and job["status"] == "queued":
        job["status"] = "canceled"
    elif job and job["status"] in ("done", "error", "canceled"):
        with jobs_lock:
            jobs.pop(job_id, None)
    return jsonify({"ok": True})


@app.get("/api/jobs/<job_id>/video")
def job_video(job_id):
    job = jobs.get(job_id)
    if not job or not job.get("result"):
        return "not found", 404
    return send_file(job["result"]["output"], mimetype="video/mp4", conditional=True)


@app.post("/api/open-output")
def open_output():
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    if hasattr(os, "startfile"):
        os.startfile(config.OUTPUT_DIR)  # Windows 탐색기로 열기
    return jsonify({"path": config.OUTPUT_DIR})


def _port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


def selftest(url=None):
    """설치 확인용: 테스트 영상을 만들어 쇼츠로 변환해 본다 (빌드 검사에서 사용)."""
    import shutil
    import subprocess
    import pipeline

    print("ffmpeg:", shutil.which("ffmpeg"), "| ffprobe:", shutil.which("ffprobe"), "| deno:", shutil.which("deno"))
    settings = config.load_settings()
    print("font:", config.find_font(settings))
    os.makedirs(config.WORK_DIR, exist_ok=True)
    src = os.path.join(config.WORK_DIR, "selftest_src.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=1280x720:d=3:r=30",
                    "-f", "lavfi", "-i", "sine=f=440:d=3", "-shortest", src], check=True)
    channel = {**config.DEFAULT_CHANNEL, "name": "selftest"}
    job = {"id": "selftest", "file": src, "title_override": "자체 점검/테스트 영상", "highlight": "테스트"}
    if url:
        job = {"id": "selftest_url", "url": url, "title_override": "다운로드/테스트"}
    res = pipeline.run_job(job, settings, channel, log=print)
    meta = pipeline.probe(res["output"])
    print("OK", res["output"], meta)
    assert (meta["w"], meta["h"]) == (1080, 1920)


def main():
    for stream in (sys.stdout, sys.stderr):  # 한글 출력이 깨지거나 오류 나지 않게
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    try:  # exe 실행 시 뜨는 로딩 화면 닫기
        import pyi_splash
        pyi_splash.close()
    except Exception:
        pass
    if "--selftest" in sys.argv:
        i = sys.argv.index("--selftest")
        selftest(sys.argv[i + 1] if len(sys.argv) > i + 1 else None)
        return
    port = int(os.environ.get("PORT", 5077))
    url = f"http://127.0.0.1:{port}"
    if _port_in_use(port):
        # 이미 켜져 있으면 화면만 다시 연다
        webbrowser.open(url)
        return
    os.makedirs(config.WORK_DIR, exist_ok=True)
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    threading.Thread(target=worker, daemon=True).start()
    print("=" * 56)
    print("  딸깍 쇼츠 공장이 실행되었습니다!")
    print(f"  인터넷 창이 자동으로 열립니다. 안 열리면 주소창에 {url}")
    print("  완성된 영상 폴더:", config.OUTPUT_DIR)
    print("  ※ 이 검은 창을 닫으면 프로그램이 꺼집니다. 쓰는 동안 그대로 두세요.")
    print("=" * 56)
    if not os.environ.get("NO_BROWSER"):
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
