param([switch]$NoOpen)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$url = 'http://127.0.0.1:3080'
$metadataFile = Join-Path $root 'harness-home\web-process.json'
$launcher = Join-Path $root 'harness-launch.cjs'
function Read-LocalHttp([string]$Address) {
    $request = [Net.HttpWebRequest]::Create($Address)
    $request.Proxy = $null
    $request.CookieContainer = New-Object Net.CookieContainer
    $request.Timeout = 3000
    $response = $request.GetResponse()
    try {
        $reader = New-Object IO.StreamReader($response.GetResponseStream())
        try { return $reader.ReadToEnd() } finally { $reader.Dispose() }
    } finally { $response.Dispose() }
}
function Read-LaunchAddress($Record) {
    if ($Record.launchUrl -and $Record.launchUrl -match '^http://127\.0\.0\.1:3080/\?token=[A-Za-z0-9_-]+$') { return [string]$Record.launchUrl }
    if ($Record.stdout -and (Test-Path -LiteralPath $Record.stdout)) {
        $logged = Get-Content -LiteralPath $Record.stdout -Raw
        $match = [regex]::Match($logged, 'http://127\.0\.0\.1:3080/\?token=[A-Za-z0-9_-]+')
        if ($match.Success) { return $match.Value }
    }
    throw 'The authenticated Harness startup address has not been written yet.'
}
function Save-Ready($Record) {
    $openUrl = Read-LaunchAddress $Record
    $null = Read-LocalHttp $openUrl
    $Record | Add-Member -MemberType NoteProperty -Name launchUrl -Value $openUrl -Force
    $Record | ConvertTo-Json | Set-Content -LiteralPath $metadataFile -Encoding UTF8
    return $openUrl
}
$mutex = [Threading.Mutex]::new($false, 'Local\STRATA-DeepSeek-Harness-Start')
$held = $false
try {
    $held = $mutex.WaitOne(0)
    if (-not $held) { Write-Output 'Harness is already starting.'; return }
    $backend = $null
    try { $backend = Read-LocalHttp 'http://127.0.0.1:8080/health' | ConvertFrom-Json } catch { }
    if (-not $backend -or -not $backend.loaded -or $backend.model -ne 'deepseek-v4.1-flash' -or $backend.max_context -lt 65536) {
        Write-Output 'Starting the local DeepSeek model with a 64K context...'
        & (Join-Path $root 'start-deepseek-for-harness.cmd')
        if ($LASTEXITCODE -ne 0) { throw 'The local DeepSeek model could not start.' }
        $backend = Read-LocalHttp 'http://127.0.0.1:8080/health' | ConvertFrom-Json
        if (-not $backend.loaded -or $backend.model -ne 'deepseek-v4.1-flash' -or $backend.max_context -lt 65536) { throw 'The expected local model did not become ready.' }
    }
    if (Test-Path -LiteralPath $metadataFile) {
        $metadata = Get-Content -LiteralPath $metadataFile -Raw | ConvertFrom-Json
        $existing = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + [int]$metadata.pid) -ErrorAction SilentlyContinue
        if ($existing -and $existing.CommandLine -like ('*' + $launcher + '*')) {
            try { $openUrl = Save-Ready $metadata }
            catch { throw 'Harness is running but the Web page is not ready; inspect its log before starting it again.' }
            Write-Output ('Harness is ready: ' + $url)
            if (-not $NoOpen) { Start-Process $openUrl }
            return
        }
    }
    $listener = Get-NetTCPConnection -LocalPort 3080 -State Listen -ErrorAction SilentlyContinue
    if ($listener) { throw 'Port 3080 is already used by another process.' }
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $stdout = Join-Path $root ('harness-home\logs\web-' + $stamp + '.stdout.log')
    $stderr = Join-Path $root ('harness-home\logs\web-' + $stamp + '.stderr.log')
    $node = Join-Path $root 'toolchains\node-24.14.0\node.exe'
    if (-not (Test-Path -LiteralPath $node)) { throw 'The local Node.js runtime is missing from F:\STRATA\toolchains.' }
    $process = Start-Process -FilePath $node -ArgumentList @($launcher,'--profile','web','--no-open','--host','127.0.0.1','--port','3080') -WorkingDirectory (Join-Path $root 'harness-workspace') -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    $metadata = [pscustomobject]@{pid=$process.Id;url=$url;stdout=$stdout;stderr=$stderr;startedAt=[DateTimeOffset]::Now.ToString('o')}
    $metadata | ConvertTo-Json | Set-Content -LiteralPath $metadataFile -Encoding UTF8
    for ($attempt=0; $attempt -lt 40; $attempt++) {
        $process.Refresh()
        if ($process.HasExited) { throw ('Harness exited. Log: ' + $stderr) }
        try { $openUrl = Save-Ready $metadata }
        catch { Start-Sleep -Seconds 1; continue }
        Write-Output ('Harness is ready: ' + $url)
        if (-not $NoOpen) { Start-Process $openUrl }
        return
    }
    throw ('Harness startup timed out. Log: ' + $stderr)
} finally {
    if ($held) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}

