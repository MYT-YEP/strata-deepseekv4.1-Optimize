@echo off
setlocal
call "F:\STRATA\strata-env.cmd"
call "F:\STRATA\terminal\current\bin\strata.cmd" launch --preset "DeepSeek-Harness-64K" --no-tui --yes %*
exit /b %errorlevel%