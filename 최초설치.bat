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
REM    1) 32비트 파이썬             (Keithley/BioLED DLL이 32비트 전용)
REM    2) VC++ 2013 재배포 (x86)    (KXCIclient.dll 이 MSVCR120.dll 을 요구)
REM    3) Git                       (업데이트 버튼용)
REM    4) 파이썬 패키지             openpyxl, pyserial
REM    5) 업데이트 연결             (복사해 온 폴더를 git 저장소로 승격)
REM    6) DLL 로드 검증 + 바탕화면 바로가기
REM ==========================================================
setlocal EnableDelayedExpansion
set "APPDIR=%~dp0"
if "%APPDIR:~-1%"=="\" set "APPDIR=%APPDIR:~0,-1%"
set "REPO_URL=https://github.com/jun0land/Kiethly_4200.git"

REM 32비트 시스템 DLL이 실제로 놓이는 폴더.
REM 64비트 Windows 에서는 SysWOW64 가 32비트용이고 System32 는 64비트용이다.
REM 여기를 헷갈리면 x64 재배포만 깔린 PC를 "이미 설치됨"으로 잘못 판정한다.
set "SYS32DIR=%SystemRoot%\System32"
if exist "%SystemRoot%\SysWOW64\kernel32.dll" set "SYS32DIR=%SystemRoot%\SysWOW64"

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
  echo          - Visual C++ 2013 재배포 패키지 ^(x86^) — vcredist_x86.exe
  echo            https://www.microsoft.com/en-us/download/details.aspx?id=40784
  echo          - git-scm.com  Git for Windows
  echo(
  pause
  exit /b 1
)
echo [1/6] winget 확인 완료
echo(

REM ---------- 32비트 파이썬 ----------
echo [2/6] 32비트 파이썬 확인 중...
py -3-32 -c "import sys" >nul 2>&1
if errorlevel 1 (
  echo       32비트 파이썬이 없습니다. 설치를 시작합니다...
  echo       ^(설치 창이 뜨면 잠시 기다려 주세요^)
  winget install --id Python.Python.3.13 --architecture x86 ^
        --source winget ^
        --accept-package-agreements --accept-source-agreements --silent
  if errorlevel 1 (
    echo(
    echo [오류] winget 이 파이썬 설치에 실패했습니다. ^(msstore 소스 문제일 수 있음^)
    echo        아래 명령을 이 창에 직접 붙여넣어 재시도해 보세요:
    echo(
    echo          winget source reset --force
    echo(
    echo        그래도 안 되면 python.org 에서 Windows installer ^(32-bit^) 를
    echo        직접 설치하세요. ^([Add python.exe to PATH] 체크 필수^)
    echo(
    pause
    exit /b 1
  )
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

REM ---------- Visual C++ 2013 재배포 패키지 (x86) ----------
REM  KXCIclient.dll 은 MSVCR120.dll 을 필요로 하는데 이건 Windows 기본
REM  설치에 **없다**. 빠지면 DLL 파일이 멀쩡히 있어도 로드가 실패하고
REM  "Could not find module ... (or one of its dependencies)" 라는,
REM  마치 경로 문제처럼 보이는 엉뚱한 오류가 난다.
REM  DLL이 32비트라 64비트 Windows 에서도 반드시 **x86** 을 깔아야 한다.
echo [3/6] Visual C++ 2013 재배포 패키지 ^(x86^) 확인 중...
if exist "%SYS32DIR%\msvcr120.dll" (
  echo       이미 설치돼 있습니다.
  goto :vc_done
)
echo       없습니다. 설치를 시작합니다...
echo       ^(관리자 권한 확인 창이 뜨면 [예] 를 누르세요^)
winget install --id Microsoft.VCRedist.2013.x86 ^
      --source winget ^
      --accept-package-agreements --accept-source-agreements --silent
if exist "%SYS32DIR%\msvcr120.dll" (
  echo       완료.
  goto :vc_done
)
echo(
echo   ****************************************************************
echo   [중요] Visual C++ 2013 ^(x86^) 설치에 실패했습니다.
echo          이게 없으면 Keithley 연결이 반드시 실패합니다.
echo          아래에서 vcredist_x86.exe 를 직접 받아 설치하세요:
echo            https://www.microsoft.com/en-us/download/details.aspx?id=40784
echo          ^(64비트 Windows 에서도 x86 을 받아야 합니다^)
echo   ****************************************************************
echo(
pause
:vc_done
echo(

REM ---------- Git ----------
echo [4/6] Git 확인 중...
where git >nul 2>&1
if errorlevel 1 (
  echo       Git 이 없습니다. 설치를 시작합니다...
  winget install --id Git.Git --source winget --accept-package-agreements --accept-source-agreements --silent
  if errorlevel 1 (
    echo       [경고] winget 으로 Git 설치에 실패했습니다.
    echo              git-scm.com 에서 Git for Windows 를 직접 설치해 주세요.
  ) else (
    echo       설치 명령 완료.
  )
) else (
  for /f "delims=" %%g in ('git --version') do echo       이미 설치됨: %%g
)
echo(

REM ---------- 파이썬 패키지 ----------
echo [5/6] 파이썬 패키지 설치 중 ^(openpyxl, pyserial^)...
py -3-32 -m pip install --upgrade --quiet pip
py -3-32 -m pip install --upgrade --quiet openpyxl pyserial
if errorlevel 1 (
  echo       [경고] 패키지 설치에 실패했습니다. 인터넷 연결을 확인하세요.
) else (
  echo       완료.
)
echo(

REM ---------- 업데이트 연결 (git 저장소로 승격) ----------
REM  런처의 '업데이트' 버튼은 git pull 이라, 이 폴더에 .git 이 있어야 동작한다.
REM  폴더를 통째로 '복사'해 온 경우 파일은 최신이어도 .git 이 없어서 업데이트가
REM  막힌다. 그래서 clone 을 다시 받는 대신, 있는 폴더를 그 자리에서 저장소로
REM  승격시킨다 (init + remote + fetch + reset).
REM
REM  ⚠ 여기서 쓰는 reset 은 --hard 가 아니라 기본(mixed)이다. 일부러 그렇게 했다.
REM     --hard 는 작업 파일을 덮어쓰는데, 그 대상에 **지금 실행 중인 이 배치
REM     파일 자신**이 포함된다. cmd.exe 는 배치 파일을 줄 단위로 그때그때 읽으므로
REM     실행 도중 파일이 바뀌면 엉뚱한 줄로 튄다. mixed reset 은 HEAD/인덱스만
REM     맞추고 파일은 건드리지 않아서 이 사고가 없다.
REM     파일 내용을 실제로 맞추는 건 맨 마지막 '저장소와 다른 파일 확인'에서
REM     사용자 확인을 받고 처리한다.
echo [6/6] 업데이트 연결 확인 중...
where git >nul 2>&1
if errorlevel 1 (
  echo       Git 이 없어 건너뜁니다. Git 설치 후 다시 실행하세요.
  goto :repo_done
)
if exist "%APPDIR%\.git" (
  echo       이미 git 저장소입니다 - 런처의 업데이트 버튼을 쓸 수 있습니다.
  goto :repo_done
)
echo       git 저장소가 아닙니다 ^(복사해 온 폴더^). 원격에 연결합니다...
pushd "%APPDIR%"
git init -b main >nul 2>&1
git remote remove origin >nul 2>&1
git remote add origin %REPO_URL%
git fetch origin --quiet
if errorlevel 1 (
  echo       [경고] 원격 저장소에서 받아오지 못했습니다.
  echo              인터넷 연결을 확인한 뒤 다시 실행하세요.
  echo              ^(주소: %REPO_URL%^)
  popd
  goto :repo_done
)
git reset --quiet origin/main
git branch --set-upstream-to=origin/main main >nul 2>&1
popd
echo       연결 완료 - 이제 런처의 "업데이트" 버튼을 쓸 수 있습니다.
:repo_done
echo(

REM ---------- 설치 검증 ----------
REM  "깔았다"가 아니라 "실제로 로드된다"를 확인한다. DLL 의존성 누락은
REM  ctypes 로 직접 열어보기 전에는 드러나지 않는다.
echo 설치 검증 중 ^(DLL 로드 테스트^)...
py -3-32 "%APPDIR%\dll_check.py" "%APPDIR%"
if errorlevel 1 (
  echo(
  echo   [경고] 위 항목이 해결되기 전에는 계측기 연결이 실패합니다.
  echo(
  pause
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

REM ---------- 저장소와 다른 파일 확인 ----------
REM  여기까지 오면 폴더는 저장소에 연결돼 있다. 다만 복사해 온 파일이 저장소
REM  최신 버전과 다를 수 있다(예전 버전을 복사했거나, 그 PC에서 손으로 고친 경우).
REM  그 상태로 두면 'git pull --ff-only' 가 거부돼서 업데이트 버튼이 막힌다.
REM  덮어쓰기는 되돌릴 수 없으므로 반드시 확인을 받는다.
REM  -uno : 추적하지 않는 파일(측정 데이터, 설정 JSON 등)은 애초에 대상이 아니다.
if not exist "%APPDIR%\.git" goto :the_end
set "DIRTY="
pushd "%APPDIR%"
for /f "delims=" %%f in ('git status --porcelain -uno 2^>nul') do set "DIRTY=1"
popd
if not defined DIRTY (
  echo 이 폴더는 저장소 최신 버전과 동일합니다.
  goto :the_end
)
echo(
echo ------------------------------------------------------------
echo  이 폴더의 아래 파일이 저장소 최신 버전과 다릅니다:
echo(
REM  core.quotepath=false : 이걸 끄지 않으면 한글 파일명이 8진수 이스케이프로
REM  깨져 나와서, 정작 어떤 파일이 다른지 사용자가 알아볼 수 없다.
pushd "%APPDIR%" & git -c core.quotepath=false status --short -uno & popd
echo(
echo  이대로 두면 런처의 업데이트 버튼이 막힙니다.
echo  저장소 버전으로 맞추면 위 파일의 로컬 수정 내용은 사라집니다.
echo  ^(측정 데이터와 설정 파일은 추적 대상이 아니라 영향 없습니다^)
echo ------------------------------------------------------------
REM  2>nul : 대화형이 아닌 환경(입력이 비어 있음)에서 choice 가 뱉는 영문
REM  오류 메시지를 감춘다. 그 경우 errorlevel 이 2 이상이 되어 아래 N 분기,
REM  즉 "그대로 둔다"로 떨어진다 - 덮어쓰지 않는 쪽이 안전한 기본값이다.
choice /c YN /n /m "저장소 최신 버전으로 맞출까요? [Y=맞춤 / N=그대로]: " 2>nul
if errorlevel 2 (
  echo(
  echo 그대로 두었습니다. 나중에 맞추려면 이 폴더에서:  git checkout -- .
  goto :the_end
)
REM  ⚠ 아래 줄은 실행 중인 이 배치 파일 자신을 덮어쓸 수 있다. cmd.exe 가
REM     파일을 다시 읽으면 엉뚱한 곳으로 튀므로, 한 줄 안에서 종료까지 끝낸다.
REM     (cmd 는 줄 단위로 읽고 파싱하므로 이 줄은 이미 메모리에 올라와 있다.
REM      goto 나 다음 줄로 넘어가면 파일을 다시 읽게 되어 위험하다.)
pushd "%APPDIR%" & git checkout -- . & popd & echo. & echo 저장소 최신 버전으로 맞췄습니다. & echo. & pause & exit /b 0

:the_end
echo(
pause
