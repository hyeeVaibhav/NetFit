<#
  run.ps1 - check the setup, then start the NIDS web app.   Usage:  .\scripts\run.ps1   (optional: -Port 5001)
#>
param([int]$Port = 5000)
Set-Location (Split-Path -Parent $PSScriptRoot)
python check_setup.py
if ($LASTEXITCODE -ne 0) { Write-Host "`nFix the items above first (see README.md)." -ForegroundColor Yellow; exit 1 }
$env:PORT = "$Port"
Write-Host "Starting NIDS app on http://127.0.0.1:$Port ..." -ForegroundColor Cyan
python app.py
