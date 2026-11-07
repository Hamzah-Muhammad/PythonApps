# Runs AIVisibilityCheck once. Meant for Windows Task Scheduler (weekly).
# Reads API keys from your user environment variables. Writes to .\results\.
$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot
$log = Join-Path $PSScriptRoot 'results\last_run.log'
New-Item -ItemType Directory -Force (Join-Path $PSScriptRoot 'results') | Out-Null
python .\aivisibility.py *>&1 | Tee-Object -FilePath $log
