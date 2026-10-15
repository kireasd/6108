@echo off
chcp 65001 >nul
cd /d %~dp0
where ffmpeg >nul 2>nul || (echo [!] FFmpeg가 필요합니다: winget install Gyan.FFmpeg & pause & exit /b)
if not exist .venv ( python -m venv .venv )
call .venv\Scripts\activate
pip install -q -r requirements.txt
python app.py
