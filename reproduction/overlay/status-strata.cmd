@echo off
setlocal
call "%~dp0strata-env.cmd"
call "%~dp0terminal\current\bin\strata.cmd" launch --status
pause
endlocal
