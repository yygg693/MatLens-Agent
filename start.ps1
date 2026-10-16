# MatLens 本地服务启动脚本（PowerShell）
# 用法：在 D:\MatLens 下执行  .\start.ps1
$ErrorActionPreference = "Stop"

$AppDir  = "D:\MatLens"
$Python  = Join-Path $AppDir ".venv\Scripts\python.exe"
$Port    = 7896
$Url     = "http://127.0.0.1:$Port/"

Set-Location $AppDir

if (-not (Test-Path $Python)) {
    Write-Host "[错误] 未找到解释器: $Python" -ForegroundColor Red
    Write-Host "       请确认 .venv 已创建于 D:\MatLens\.venv" -ForegroundColor Red
    exit 1
}

# ── 端口占用检查：被占则提示并退出，不重复拉起第二个服务 ──
$occupied = $false
try {
    $listen = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
    if ($listen) { $occupied = $true }
} catch {
    $occupied = $false
}

if ($occupied) {
    Write-Host "[提示] 端口 $Port 已被占用，MatLens 似乎已在运行。" -ForegroundColor Yellow
    Write-Host "       访问地址: $Url" -ForegroundColor Yellow
    exit 0
}

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  MatLens 材料之镜  -  本地服务" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  解释器 : $Python"
Write-Host "  启动   : python -m matlens_kit.api.server --port $Port"
Write-Host "  地址   : $Url"
Write-Host "  停止   : 按 Ctrl+C"
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

& $Python -m matlens_kit.api.server --port $Port
