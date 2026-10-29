@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-harness-fast.ps1" %*
set "STRATA_START_EXIT=%errorlevel%"
if not "%STRATA_START_EXIT%"=="0" pause
exit /b %STRATA_START_EXIT%
