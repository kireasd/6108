@echo off
chcp 65001 >nul
title 딸깍 쇼츠 공장
setlocal

set "REPO=kireasd/6108"
for /f "usebackq delims=" %%d in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "DESK=%%d"
if "%DESK%"=="" set "DESK=%USERPROFILE%\Desktop"
set "DIR=%DESK%\DdalkkakShorts"
set "EXE=%DIR%\DdalkkakShorts.exe"
if not exist "%DIR%" mkdir "%DIR%"

echo.
echo  ==============================================
echo     딸깍 쇼츠 공장 - 시작 도우미
echo  ==============================================
echo.
echo  최신 버전을 확인하는 중입니다...

set "LATEST="
for /f "usebackq delims=" %%v in (`powershell -NoProfile -Command "try { (Invoke-RestMethod -UseBasicParsing https://api.github.com/repos/%REPO%/releases/latest).tag_name } catch { '' }"`) do set "LATEST=%%v"
set "CUR="
if exist "%DIR%\version.txt" set /p CUR=<"%DIR%\version.txt"

if "%LATEST%"=="" goto :nocheck
if exist "%EXE%" if "%LATEST%"=="%CUR%" goto :run

echo.
echo  프로그램을 내려받는 중입니다. 약 230MB, 인터넷에 따라 1~5분 걸려요.
echo  이 창을 닫지 말고 기다려 주세요...
echo.
curl.exe -L --fail --progress-bar -o "%EXE%.part" "https://github.com/%REPO%/releases/download/%LATEST%/DdalkkakShorts.exe"
if errorlevel 1 goto :dlfail
move /y "%EXE%.part" "%EXE%" >nul
> "%DIR%\version.txt" echo %LATEST%
echo  내려받기 완료! 버전: %LATEST%
goto :run

:nocheck
if exist "%EXE%" goto :run
echo.
echo  [!] 인터넷에 연결할 수 없어서 프로그램을 받지 못했어요.
echo      인터넷 연결을 확인한 뒤 이 파일을 다시 더블클릭해 주세요.
pause
exit /b 1

:dlfail
if exist "%EXE%.part" del "%EXE%.part"
echo.
echo  [!] 내려받기에 실패했어요. 잠시 후 이 파일을 다시 더블클릭해 주세요.
pause
exit /b 1

:run
echo.
echo  프로그램을 실행합니다. 10초쯤 뒤 인터넷 창이 열려요.
echo  완성된 영상은 바탕화면의 DdalkkakShorts 폴더 안 "완성된 쇼츠" 폴더에 저장돼요.
if "%SHORTS_NO_LAUNCH%"=="1" exit /b 0
start "" /D "%DIR%" "%EXE%"
timeout /t 5 >nul
exit /b 0
