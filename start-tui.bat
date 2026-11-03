@echo off
chcp 65001 >nul
title MatLens 材料之镜 - 终端界面 (TUI)
cd /d "%~dp0"
set MATLENS_HOME=%USERPROFILE%\.matlens

REM Use the project's own virtualenv. The previous hardcoded interpreter
REM (a WorkBuddy-managed python env) no longer exists on this machine, so
REM this script failed with "not recognized" before it ever reached the CLI.
set "PYTHON=%~dp0.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo [错误] 未找到解释器: %PYTHON%
    echo        请先在项目目录执行: uv sync
    pause
    exit /b 1
)

echo 正在启动 MatLens 终端界面...
"%PYTHON%" -m matlens_cli.main
pause

