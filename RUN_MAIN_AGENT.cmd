@echo off
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"
"D:\download\anaconda3\envs\gpt-researcher\python.exe" -m research_main_agent %*
if errorlevel 1 pause
endlocal
