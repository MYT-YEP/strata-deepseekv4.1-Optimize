$ErrorActionPreference = 'Stop'
$metadataFile = Join-Path $PSScriptRoot 'harness-home\web-process.json'
if (-not (Test-Path -LiteralPath $metadataFile)) { Write-Output 'Harness is not running.'; exit 0 }
$metadata = Get-Content -LiteralPath $metadataFile -Raw | ConvertFrom-Json
$entry = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + [int]$metadata.pid) -ErrorAction SilentlyContinue
$launcher = Join-Path $PSScriptRoot 'harness-launch.cjs'
if (-not $entry) { Write-Output 'Harness is already stopped.'; exit 0 }
if ($entry.CommandLine -notlike ('*' + $launcher + '*')) { throw 'The saved PID belongs to another process; nothing was stopped.' }
Stop-Process -Id ([int]$metadata.pid) -ErrorAction Stop
Write-Output 'Harness Web stopped. The local DeepSeek model remains available.'
