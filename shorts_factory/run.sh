#!/usr/bin/env bash
cd "$(dirname "$0")"
command -v ffmpeg >/dev/null || { echo "FFmpeg가 필요합니다 (brew install ffmpeg / apt install ffmpeg)"; exit 1; }
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install -q -r requirements.txt
python app.py
