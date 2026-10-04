@echo off
chcp 65001 >nul
rem 업데이트 중에 이 파일 자신도 바뀌므로, 임시 폴더에 복사본을 만들어 그걸로 실행한다
if not "%~1"=="--run" (
    copy /y "%~f0" "%TEMP%\shorts-maker-update.bat" >nul
    rem call 없이 실행해야 원래 파일로 돌아오지 않는다
    "%TEMP%\shorts-maker-update.bat" --run "%~dp0."
)
set "APPDIR=%~f2"
cd /d "%APPDIR%"
title 쇼츠 자동 제작기 - 업데이트
rem 새 버전을 받아 올 GitHub 주소 (저장소/브랜치)
set "REPO=kireasd/6108"
set "BRANCH=claude/dazzling-davinci-1dn758"

if not exist venv\Scripts\python.exe (
    echo 아직 설치가 안 되어 있어요. 먼저 install.bat을 실행해 주세요.
    pause
    exit /b 1
)
echo 새 버전을 내려받는 중...
set "TMPDIR=%TEMP%\shorts-maker-update"
if exist "%TMPDIR%" rmdir /s /q "%TMPDIR%"
mkdir "%TMPDIR%"
powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri 'https://github.com/%REPO%/archive/refs/heads/%BRANCH%.zip' -OutFile '%TMPDIR%\update.zip'; Expand-Archive -Path '%TMPDIR%\update.zip' -DestinationPath '%TMPDIR%' -Force"
set "NEWDIR="
for /d %%d in ("%TMPDIR%\*") do if exist "%%d\shorts-maker\app.py" set "NEWDIR=%%d\shorts-maker"
if not defined NEWDIR (
    echo.
    echo [문제] 새 버전을 내려받지 못했어요. 인터넷 연결을 확인하고 다시 실행해 주세요.
    pause
    exit /b 1
)

echo 프로그램 파일을 바꾸는 중... (설정, 배경음악, AI는 그대로 둬요)
robocopy "%NEWDIR%" "%APPDIR%" /E /XD venv work /XF settings.json /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
    echo.
    echo [문제] 파일을 바꾸지 못했어요. 프로그램(run.bat 검은 창)을 끄고 다시 실행해 주세요.
    pause
    exit /b 1
)

echo 새로 필요한 부품이 있으면 설치하는 중...
venv\Scripts\python.exe -m pip install -r requirements.txt -q
rem 유튜브가 자주 바뀌어서 유튜브 도우미는 항상 최신으로
venv\Scripts\python.exe -m pip install -U "yt-dlp[default]" -q
rmdir /s /q "%TMPDIR%"

echo.
echo ============================================
echo   업데이트 완료! 프로그램을 다시 켜 주세요.
echo ============================================
pause
