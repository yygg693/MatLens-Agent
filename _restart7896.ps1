$env:HF_HUB_DISABLE_XET = "1"
$proc = Get-NetTCPConnection -LocalPort 7896 -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty OwningProcess
if ($proc) { Stop-Process -Id $proc -Force; Write-Host "killed PID $proc" } else { Write-Host "no process" }
Start-Sleep -Seconds 2
Start-Process -FilePath "D:\Python313\python.exe" -ArgumentList "-m","matlens_kit.api.server","--port","7896" -WorkingDirectory "D:\MatLens" -RedirectStandardOutput "D:\MatLens\_server7896.log" -RedirectStandardError "D:\MatLens\_server7896_err.log" -NoNewWindow
Start-Sleep -Seconds 8
$proc = Get-NetTCPConnection -LocalPort 7896 -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty OwningProcess
if ($proc) { Write-Host "restarted PID $proc" } else { Write-Host "FAILED" }
