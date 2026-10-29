$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$tuning = Join-Path $root 'tuning\20tok-goal'
$metaPath = Join-Path $tuning 'fast-mode.json'
$manager = Join-Path $root 'fast-mode-manager.py'
if (-not (Test-Path -LiteralPath $metaPath)) { Write-Output 'Fast mode is not running.'; exit 0 }
$metadata = Get-Content -LiteralPath $metaPath -Raw | ConvertFrom-Json
$prefix = [IO.Path]::GetFullPath($tuning) + '\xolotl-trial-'
$statePath = [IO.Path]::GetFullPath([string]$metadata.state)
$stopPath = [IO.Path]::GetFullPath([string]$metadata.stop_flag)
if (-not $statePath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) -or
    -not $statePath.EndsWith('-state.json', [StringComparison]::OrdinalIgnoreCase) -or
    -not $stopPath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) -or
    -not $stopPath.EndsWith('-stop.txt', [StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected fast-mode paths.' }
if (-not (Test-Path -LiteralPath $statePath)) { throw 'Fast-mode state is missing; no process was stopped.' }
$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
if ($state.phase -eq 'done' -and -not $state.need_restore) { Write-Output 'Fast mode is already stopped; the original model was restored.'; exit 0 }
$process = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + [int]$metadata.pid) -ErrorAction SilentlyContinue
if (-not $process -or $process.Name -ne 'python.exe' -or $process.CommandLine -notlike ('*' + $manager + '*')) {
    throw 'The fast manager is not running; inspect its state and watchdog log before starting another copy.'
}
[IO.File]::WriteAllText($stopPath, 'stop requested')
Write-Output 'Stopping fast mode and restoring the original model...'
for ($i = 0; $i -lt 180; $i++) {
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    if ($state.phase -eq 'done' -and -not $state.need_restore) {
        Write-Output 'Fast mode stopped; the original 64K model is restored.'
        exit 0
    }
    if ($state.phase -eq 'restore_failed') { throw ('Original model recovery failed; inspect ' + $state.watchdog_log) }
    Start-Sleep -Seconds 1
}
throw 'Fast mode did not finish restoring in time; inspect its controller and watchdog logs.'
