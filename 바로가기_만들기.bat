@echo off
REM ==========================================================
REM  바탕화면에 "PD 측정 스테이션" 바로가기를 만든다.
REM  이 파일을 한 번만 더블클릭하면 된다.
REM
REM  어느 컴퓨터/어느 폴더에 두든 동작한다:
REM   - 경로를 %~dp0(이 파일이 있는 폴더)로 잡으므로 위치 무관
REM   - 파이썬 실행기는 pyw.exe -> pythonw.exe 순으로 자동 탐색
REM ==========================================================
setlocal
set "APPDIR=%~dp0"
if "%APPDIR:~-1%"=="\" set "APPDIR=%APPDIR:~0,-1%"

echo 바탕화면에 바로가기를 만드는 중...
echo   대상 폴더: %APPDIR%
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$appdir = '%APPDIR%';" ^
  "$target = $null;" ^
  "foreach ($c in @('pyw.exe','pythonw.exe')) { $g = Get-Command $c -ErrorAction SilentlyContinue; if ($g) { $target = $g.Source; break } };" ^
  "if (-not $target) {" ^
  "  Write-Host '';" ^
  "  Write-Host '[오류] 파이썬을 찾을 수 없습니다.' -ForegroundColor Red;" ^
  "  Write-Host '  python.org 에서 Windows installer (32-bit) 를 설치하고,';" ^
  "  Write-Host '  설치 화면에서 [Add python.exe to PATH] 를 체크하세요.';" ^
  "  exit 1 };" ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$lnkPath = Join-Path $ws.SpecialFolders('Desktop') 'PD 측정 스테이션.lnk';" ^
  "$lnk = $ws.CreateShortcut($lnkPath);" ^
  "$lnk.TargetPath = $target;" ^
  "$lnk.Arguments = ('\"' + (Join-Path $appdir 'launcher.pyw') + '\"');" ^
  "$lnk.WorkingDirectory = $appdir;" ^
  "$lnk.IconLocation = 'shell32.dll,13';" ^
  "$lnk.Description = 'Keithley 4200 + BioLED 측정 스테이션 런처';" ^
  "$lnk.Save();" ^
  "Write-Host ('  파이썬 실행기: ' + $target);" ^
  "Write-Host ('  바로가기 생성: ' + $lnkPath) -ForegroundColor Green"

echo.
if errorlevel 1 (
  echo 바로가기를 만들지 못했습니다. 위 메시지를 확인하세요.
) else (
  echo 완료. 바탕화면의 "PD 측정 스테이션" 아이콘을 더블클릭하세요.
)
pause
