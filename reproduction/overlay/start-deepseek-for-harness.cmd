@echo off
setlocal
call "%~dp0strata-env.cmd"
call "%~dp0terminal\current\bin\strata.cmd" launch --family deepseek41 --model ist-das-2.25bpw --data-dir "%~dp0data" --context 64k --speed full --dspark auto --tune skip --save-preset "DeepSeek-Harness-64K" --restart --yes --no-tui
exit /b %errorlevel%

