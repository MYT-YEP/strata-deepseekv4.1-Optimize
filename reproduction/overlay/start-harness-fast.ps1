param([switch]$NoOpen)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$tuning = Join-Path $root 'tuning\20tok-goal'
$metaPath = Join-Path $tuning 'fast-mode.json'
$manager = Join-Path $root 'fast-mode-manager.py'
$python = Join-Path $root 'terminal\current\python\python.exe'
$helper = Join-Path $tuning 'restore-original-norestart.cmd'

function Read-LocalHttp([string]$Address) {
    $request = [Net.HttpWebRequest]::Create($Address)
    $request.Proxy = $null
    $request.Timeout = 5000
    $request.CookieContainer = [Net.CookieContainer]::new()
    $response = $request.GetResponse()
    try {
        $reader = [IO.StreamReader]::new($response.GetResponseStream())
        try { return $reader.ReadToEnd() } finally { $reader.Dispose() }
    } finally { $response.Dispose() }
}
function Get-FastReady($Record) {
    if (-not $Record.state -or -not $Record.web_log) { return $null }
    $statePath = [IO.Path]::GetFullPath([string]$Record.state)
    $webLog = [IO.Path]::GetFullPath([string]$Record.web_log)
    $prefix = [IO.Path]::GetFullPath($tuning) + '\xolotl-trial-'
    if (-not $statePath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) -or
        -not $statePath.EndsWith('-state.json', [StringComparison]::OrdinalIgnoreCase) -or
        -not $webLog.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) -or
        -not $webLog.EndsWith('-fast-web.out.log', [StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected fast-mode paths.' }
    if (-not (Test-Path -LiteralPath $statePath) -or -not (Test-Path -LiteralPath $webLog)) { return $null }
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    if (-not $state.web_ready -or $state.phase -ne 'candidate_ready') { return $null }
    $match = [regex]::Match((Get-Content -LiteralPath $webLog -Raw), 'http://127\.0\.0\.1:3081/\?token=[A-Za-z0-9_-]+')
    if (-not $match.Success) { return $null }
    $null = Read-LocalHttp $match.Value
    return $match.Value
}

$mutex = [Threading.Mutex]::new($false, 'Local\STRATA-20tok-fast-start')
$held = $false
try {
    $held = $mutex.WaitOne(0)
    if (-not $held) { throw 'Fast mode is already starting.' }
    $existing = $null
    if (Test-Path -LiteralPath $metaPath) {
        $metadata = Get-Content -LiteralPath $metaPath -Raw | ConvertFrom-Json
        $existing = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + [int]$metadata.pid) -ErrorAction SilentlyContinue
        if ($existing -and $existing.Name -eq 'python.exe' -and $existing.CommandLine -like ('*' + $manager + '*')) {
            $url = Get-FastReady $metadata
            if (-not $url) { throw 'Fast mode is already starting; wait for it to become ready.' }
            Write-Output 'Fast Harness is ready on http://127.0.0.1:3081 (text only; separate sessions).'
            if (-not $NoOpen) { Start-Process -FilePath $url }
            return
        }
    }
    foreach ($port in @(8150, 3081)) {
        if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) { throw "Port $port is already in use." }
    }
    if (-not (Test-Path -LiteralPath $manager) -or -not (Test-Path -LiteralPath $helper)) { throw 'Fast-mode components are missing.' }
    & $helper
    if ($LASTEXITCODE -ne 0) { throw 'The original model could not be made ready without restarting another service.' }
    $health = Read-LocalHttp 'http://127.0.0.1:8080/health' | ConvertFrom-Json
    $status = Read-LocalHttp 'http://127.0.0.1:8080/status' | ConvertFrom-Json
    if (-not $health.loaded -or $health.model -ne 'deepseek-v4.1-flash' -or $health.max_context -ne 65536) { throw 'The expected original 64K model is not ready.' }
    if ($status.busy -or $status.queued) { throw 'The original model is busy; no switch was made.' }
    $tag = Get-Date -Format 'yyyyMMdd-HHmmss'
    $out = Join-Path $tuning ('fast-manager-launch-' + $tag + '.out.log')
    $err = Join-Path $tuning ('fast-manager-launch-' + $tag + '.err.log')
    $proc = Start-Process -FilePath $python -ArgumentList @('-I','-X','utf8',$manager) -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err -PassThru
    Write-Output 'Starting the local text-only fast model. The normal model will be restored when fast mode stops.'
    for ($i = 0; $i -lt 240; $i++) {
        $proc.Refresh()
        if ($proc.HasExited) { throw ('Fast mode did not start; inspect ' + $err) }
        if (Test-Path -LiteralPath $metaPath) {
            $metadata = Get-Content -LiteralPath $metaPath -Raw | ConvertFrom-Json
            if ([int]$metadata.pid -eq $proc.Id) {
                try { $url = Get-FastReady $metadata } catch { $url = $null }
                if ($url) {
                    Write-Output 'Fast Harness is ready on http://127.0.0.1:3081 (text only; separate sessions).'
                    Write-Output 'Expert-routing bias changes answers; use the original mode for full quality and images.'
                    if (-not $NoOpen) { Start-Process -FilePath $url }
                    return
                }
            }
        }
        Start-Sleep -Seconds 1
    }
    if ($metadata -and [int]$metadata.pid -eq $proc.Id -and $metadata.stop_flag) {
        $stopPath = [IO.Path]::GetFullPath([string]$metadata.stop_flag)
        if ($stopPath.StartsWith(([IO.Path]::GetFullPath($tuning) + '\xolotl-trial-'), [StringComparison]::OrdinalIgnoreCase) -and
            $stopPath.EndsWith('-stop.txt', [StringComparison]::OrdinalIgnoreCase)) {
            [IO.File]::WriteAllText($stopPath, 'startup timeout')
        }
    }
    throw ('Fast mode did not become ready in time; inspect ' + $err)
} finally {
    if ($held) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
