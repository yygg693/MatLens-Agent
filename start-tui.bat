@echo off
chcp 65001 >nul
title MatLens 材料之镜 - 终端界面 (TUI)
cd /d "%~dp0"
set MATLENS_HOME=%USERPROFILE%\.matlens
echo 正在启动 MatLens 终端界面...
"C:\Users\22091\.workbuddy\binaries\python\envs\matlens2\Scripts\python.exe" matlens
pause
