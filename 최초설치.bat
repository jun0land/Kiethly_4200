@echo off
chcp 65001 >nul
REM ==========================================================
REM  최초 설치 — 이 파일만 더블클릭하면 필요한 것이 전부 깔린다.
REM
REM  ⚠ 이 파일은 **파이썬 없이 동작**해야 한다.
REM     런처(launcher.pyw)는 그 자체가 파이썬 프로그램이라, 파이썬이
REM     없는 새 컴퓨터에서는 실행조차 안 된다. 그래서 파이썬 설치까지
REM     책임지는 이 배치 파일이 따로 필요하다.
REM
REM  설치 목록
REM    1) 32비트 파이썬  (Keithley/BioLED DLL이 32비트 전용)
REM    2) Git            (업데이트 버튼용)
REM    3) 파이썬 패키지  openpyxl, pyserial
REM    4) 바탕화면 바로가기
REM ==========================================================
setlocal EnableDelayedExpansion
set "APPDIR=%~dp0"
if "%APPDIR:~-1%"=="\" set "APPDIR=%APPDIR:~0,-1%"

echo(
echo ============================================================
echo   PD 측정 스테이션 - 최초 설치
echo   폴더: %APPDIR%
echo ============================================================
echo(

REM ---------- winget 확인 ----------
where winget >nul 2>&1
if errorlevel 1 (
  echo [경고] winget 을 찾을 수 없습니다.
  echo        Windows 10 1809 이상 / Windows 11 이면 보통 있습니다.
  echo        Microsoft Store 에서 "앱 설치 관리자"를 설치한 뒤 다시 실행하세요.
  echo(
  echo        winget 없이 진행하려면 아래를 직접 설치하세요:
  echo          - python.org  Windows installer ^(32-bit^)  [Add python.exe to PATH 체크]
  echo          - git-scm.com  Git for Windows
  echo(
  pause
  exit /b 1
)
echo [1/4] winget 확인 완료
echo(

REM ---------- 32비트 파이썬 ----------
echo [2/4] 32비트 파이썬 확인 중...
py -3-32 -c "import sys" >nul 2>&1
if errorlevel 1 (
  echo       32비트 파이썬이 없습니다. 설치를 시작합니다...
  echo       ^(설치 창이 뜨면 잠시 기다려 주세요^)
  winget install --id Python.Python.3.13 --architecture x86 ^
        --accept-package-agreements --accept-source-agreements --silent
  echo       설치 명령 완료. PATH 반영을 위해 확인합니다...
  py -3-32 -c "import sys" >nul 2>&1
  if errorlevel 1 (
    echo(
    echo [중요] 파이썬은 설치됐지만 이 창에서는 아직 인식되지 않습니다.
    echo        이 창을 닫고 최초설치.bat 을 **한 번 더** 실행해 주세요.
    echo        ^(새 창에서 PATH가 반영됩니다^)
    echo(
    pause
    exit /b 0
  )
) else (
  echo       이미 설치돼 있습니다.
)
for /f "delims=" %%v in ('py -3-32 -c "import sys,struct;print(str(struct.calcsize(chr(80))*8)+'bit Python '+sys.version.split()[0])"') do echo       %%v
echo(

REM ---------- Git ----------
echo [3/4] Git 확인 중...
where git >nul 2>&1
if errorlevel 1 (
  echo       Git 이 없습니다. 설치를 시작합니다...
  winget install --id Git.Git --accept-package-agreements --accept-source-agreements --silent
  echo       설치 명령 완료.
) else (
  for /f "delims=" %%g in ('git --version') do echo       이미 설치됨: %%g
)
echo(

REM ---------- 파이썬 패키지 ----------
echo [4/4] 파이썬 패키지 설치 중 ^(openpyxl, pyserial^)...
py -3-32 -m pip install --upgrade --quiet pip
py -3-32 -m pip install --upgrade --quiet openpyxl pyserial
if errorlevel 1 (
  echo       [경고] 패키지 설치에 실패했습니다. 인터넷 연결을 확인하세요.
) else (
  echo       완료.
)
echo(

REM ---------- 바로가기 ----------
echo 바탕화면 바로가기를 만드는 중...
call "%APPDIR%\바로가기_만들기.bat" >nul 2>&1
if exist "%USERPROFILE%\Desktop\PD 측정 스테이션.lnk" (
  echo       완료.
) else (
  echo       [참고] 바로가기 생성에 실패했습니다. 바로가기_만들기.bat 을 직접 실행해 보세요.
)

echo(
echo ============================================================
echo   설치가 끝났습니다.
echo   바탕화면의 "PD 측정 스테이션" 아이콘을 더블클릭하세요.
echo ============================================================
echo(
pause
