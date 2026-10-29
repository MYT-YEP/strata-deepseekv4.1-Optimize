@echo off
setlocal
call "%~dp0strata-env.cmd"
call "%~dp0terminal\current\bin\strata.cmd" launch --family deepseek41 --model ist-das-2.25bpw --data-dir "%~dp0data" --context 8k --speed full --dspark auto --tune skip --restart --yes --no-tui --open
if errorlevel 1 pause
endlocal
