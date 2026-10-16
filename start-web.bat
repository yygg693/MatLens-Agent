@echo off
chcp 65001 >nul
title MatLens 材料之镜 - Gradio 轻量版
cd /d "%~dp0"
set MATLENS_HOME=%USERPROFILE%\.matlens
set GRADIO_ANALYTICS_ENABLED=False
set HF_HUB_OFFLINE=1
REM ═══════════════════════════════════════════════════════════════
REM  MatLens 三种 Web 入口（2026-08 收敛说明）
REM   1) start-matlens.bat  (FastAPI, :7896)  ★ 主入口 / 生产使用
REM      完整工作台：智能对话·知识库·工具中心·实验·论文·记忆图谱·设置
REM   2) start-web.bat      (Gradio,   :7860)  轻量演示版（本脚本）
REM      仅对话/知识库/工具中心三块，适合快速分享或低资源演示；
REM      功能与主入口重叠，新功能优先落在主入口。
REM   3) matlens dashboard  (Hermes 原生)       上游自带，保留不毁；
REM      MatLens 默认不主推，仅供需要 Hermes 原生能力的场景。
REM ═══════════════════════════════════════════════════════════════
echo 正在启动 MatLens Gradio 轻量版，浏览器将自动打开 http://127.0.0.1:7860 ...
echo （正式使用请用 start-matlens.bat 启动主工作台 :7896）
start "" http://127.0.0.1:7860
"C:\Users\22091\.workbuddy\binaries\python\envs\matlens2\Scripts\python.exe" matlens web --port 7860
pause
