@echo off
REM ==========================================================
REM  바탕화면에 "PD 측정 스테이션" 바로가기를 만든다.
REM  이 파일을 한 번만 더블클릭하면 된다.
REM ==========================================================
setlocal
set "APPDIR=%~dp0"
REM 끝의 백슬래시 제거
if "%APPDIR:~-1%"=="\" set "APPDIR=%APPDIR:~0,-1%"

echo 바탕화면에 바로가기를 만드는 중...
echo   대상 폴더: %APPDIR%

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$desktop = $ws.SpecialFolders('Desktop');" ^
  "$lnk = $ws.CreateShortcut((Join-Path $desktop 'PD 측정 스테이션.lnk'));" ^
  "$pyw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source;" ^
  "if (-not $pyw) { $pyw = 'pythonw.exe' };" ^
  "$lnk.TargetPath = $pyw;" ^
  "$lnk.Arguments = '\"%APPDIR%\launcher.pyw\"';" ^
  "$lnk.WorkingDirectory = '%APPDIR%';" ^
  "$lnk.IconLocation = 'shell32.dll,13';" ^
  "$lnk.Description = 'Keithley 4200 + BioLED 측정 스테이션 런처';" ^
  "$lnk.Save();" ^
  "Write-Host ('만들어짐: ' + (Join-Path $desktop 'PD 측정 스테이션.lnk'))"

echo.
echo 완료. 바탕화면의 "PD 측정 스테이션" 아이콘을 더블클릭하세요.
pause
