@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist venv\Scripts\pythonw.exe (
    echo 먼저 install.bat을 더블클릭해서 설치해 주세요.
    pause
    exit /b 1
)
set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
curl -s http://localhost:11434 >nul 2>nul || (if exist "%OLLAMA%" start "" /min "%OLLAMA%" serve)
rem pythonw = 검은 창 없이 프로그램 창만 띄운다
start "" venv\Scripts\pythonw.exe app.py
