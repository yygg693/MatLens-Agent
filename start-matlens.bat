@echo off
chcp 65001 >nul
title MatLens 服务
setlocal enabledelayedexpansion

set "APP_DIR=D:\MatLens"
set "PYTHON=%APP_DIR%\.venv\Scripts\python.exe"
set "PORT=7896"
set "URL=http://127.0.0.1:%PORT%/"

cd /d "%APP_DIR%"

if not exist "%PYTHON%" (
    echo [错误] 未找到解释器: %PYTHON%
    echo        请确认 .venv 已创建于 D:\MatLens\.venv
    pause
    exit /b 1
)

REM ── 端口占用检查：已在运行则只提示并打开浏览器，不重复拉起 ──
netstat -ano 2>nul | findstr /r ":%PORT% .*LISTENING" >nul
if !errorlevel!==0 (
    echo [提示] 端口 %PORT% 已被占用，MatLens 似乎已在运行。
    echo        访问地址: %URL%
    start "" "%URL%"
    pause
    exit /b 0
)

echo ============================================
echo   MatLens 材料之镜  -  本地服务
echo ============================================
echo   解释器 : %PYTHON%
echo   启动   : python -m matlens_kit.api.server --port %PORT%
echo   地址   : %URL%
echo   停止   : 关闭本窗口（或按 Ctrl+C）
echo ============================================
echo.

"%PYTHON%" -m matlens_kit.api.server --port %PORT%

echo.
echo [服务已退出] 按任意键关闭窗口。
pause >nul
endlocal
