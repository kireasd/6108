@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 쇼츠 자동 제작기 - 설치
echo ============================================
echo   쇼츠 자동 제작기 설치를 시작합니다
echo   (처음 한 번만 하면 돼요. 20~40분 걸릴 수 있어요)
echo ============================================
echo.

rem ---------- 1. 파이썬 ----------
set "PY="
for /f "delims=" %%i in ('py -3.11 -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%i"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PY (
    echo [1/4] 파이썬을 설치하는 중...
    winget install -e --id Python.Python.3.11 --scope user --accept-package-agreements --accept-source-agreements
    set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
) else (
    echo [1/4] 파이썬이 이미 있어요.
)
if not exist "%PY%" (
    echo.
    echo [문제] 파이썬 설치에 실패했어요. https://www.python.org/downloads/ 에서 3.11 버전을 직접 설치한 뒤 다시 실행해 주세요.
    pause
    exit /b 1
)

rem ---------- 2. 프로그램 부품 ----------
echo.
echo [2/4] 프로그램 부품을 내려받는 중... (몇 분 걸려요)
if not exist venv\Scripts\python.exe "%PY%" -m venv venv
venv\Scripts\python.exe -m pip install --upgrade pip -q
venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [문제] 부품 설치에 실패했어요. 인터넷 연결을 확인하고 다시 실행해 주세요.
    pause
    exit /b 1
)

rem ---------- 3. Ollama (내 컴퓨터 AI) ----------
echo.
set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if exist "%OLLAMA%" (
    echo [3/4] Ollama가 이미 있어요.
) else (
    echo [3/4] Ollama를 설치하는 중...
    winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements
)
if not exist "%OLLAMA%" (
    echo.
    echo [문제] Ollama 설치에 실패했어요. https://ollama.com/download 에서 직접 설치한 뒤 다시 실행해 주세요.
    pause
    exit /b 1
)

rem ---------- 4. AI 모델 ----------
echo.
echo [4/4] AI 모델을 내려받는 중... (약 8GB, 인터넷 속도에 따라 10~30분)
curl -s http://localhost:11434 >nul 2>nul || (start "" /min "%OLLAMA%" serve & timeout /t 5 /nobreak >nul)
"%OLLAMA%" pull gemma3:12b
if errorlevel 1 (
    echo.
    echo [문제] AI 모델을 내려받지 못했어요. install.bat을 한 번 더 실행해 주세요.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   설치 완료! 이제 run.bat을 더블클릭하세요.
echo ============================================
pause
