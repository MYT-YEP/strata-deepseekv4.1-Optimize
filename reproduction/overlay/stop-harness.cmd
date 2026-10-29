@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-harness-fast.ps1" %*
set "STRATA_STOP_EXIT=%errorlevel%"
if not "%STRATA_STOP_EXIT%"=="0" pause
exit /b %STRATA_STOP_EXIT%
