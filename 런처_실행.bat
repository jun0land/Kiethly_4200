@echo off
REM 바로가기를 안 만들었거나 바로가기가 동작하지 않을 때 쓰는 실행 파일.
REM 어느 컴퓨터/폴더에서든 동작하도록 파이썬 실행기를 자동 탐색한다.
cd /d "%~dp0"

where pyw.exe >nul 2>&1 && (
  start "" pyw.exe "launcher.pyw"
  exit /b
)
where pythonw.exe >nul 2>&1 && (
  start "" pythonw.exe "launcher.pyw"
  exit /b
)

echo [오류] 파이썬을 찾을 수 없습니다.
echo.
echo   python.org 에서 Windows installer (32-bit) 를 설치하고,
echo   설치 화면에서 [Add python.exe to PATH] 를 체크하세요.
echo.
pause
