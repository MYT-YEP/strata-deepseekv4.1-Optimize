@echo off
"%~dp0toolchains\node-24.14.0\node.exe" "%~dp0harness-launch.cjs" %*
exit /b %errorlevel%
