@echo off
REM 바로가기를 안 만들었거나 바로가기가 동작하지 않을 때 쓰는 실행 파일.
REM (평소에는 바탕화면 바로가기를 쓰면 된다)
cd /d "%~dp0"
start "" pythonw.exe "launcher.pyw"
