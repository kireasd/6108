@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 쇼츠 자동 제작기
if not exist venv\Scripts\python.exe (
    echo 먼저 install.bat을 더블클릭해서 설치해 주세요.
    pause
    exit /b 1
)
set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
curl -s http://localhost:11434 >nul 2>nul || (if exist "%OLLAMA%" start "" /min "%OLLAMA%" serve)
echo 쇼츠 자동 제작기를 켜는 중... 잠시 후 인터넷 창이 열려요.
echo 이 검은 창을 닫으면 프로그램이 꺼져요. 쓰는 동안은 열어 두세요.
echo.
venv\Scripts\python.exe app.py
pause
