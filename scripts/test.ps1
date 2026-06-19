# ProxyHub — Node connectivity test script (Windows PowerShell 5.1+)
# Usage:
#   .\test.ps1 -Action tcp_ping -Address <a> -Port <p> -Timeout <t> -Tag <tag>
#   .\test.ps1 -Action url_test -ConfigPath <p> -BinType <t> -BinPath <b> -LocalPort <p> -TestUrl <u> -CurlTimeout <t> -Tag <tag>
#
# Output: JSON line to stdout. Exit 0 on success.

param(
    [string]$Action,

    # TCP Ping params
    [string]$Address,
    [int]$Port,
    [int]$Timeout = 3,
    # URL Test params
    [string]$ConfigPath,
    [string]$BinType,
    [string]$BinPath,
    [int]$LocalPort,
    [string]$TestUrl,
    [int]$CurlTimeout = 10,
    # Common
    [string]$Tag = "unknown"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8

# ============================================================
# JSON output helpers
# ============================================================

function Write-JsonResult {
    param($Result)
    $json = $Result | ConvertTo-Json -Compress -Depth 4
    Write-Output $json
}

# ============================================================
# TCP Ping
# ============================================================

function Invoke-TcpPing {
    param($Addr, $P, $Tmo, $Tg)

    $tcp = $null
    try {
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        $tcp = New-Object System.Net.Sockets.TcpClient
        $ar = $tcp.BeginConnect($Addr, $P, $null, $null)
        if ($ar.AsyncWaitHandle.WaitOne([TimeSpan]::FromSeconds($Tmo))) {
            $tcp.EndConnect($ar)
            $tcp.Close()
            $sw.Stop()
            Write-JsonResult @{ success = $true; latency_ms = $sw.ElapsedMilliseconds }
        }
        else {
            Write-JsonResult @{ success = $false; error = "connection timed out" }
        }
    }
    catch {
        Write-JsonResult @{ success = $false; error = $_.Exception.Message }
    }
    finally {
        if ($tcp) { $tcp.Dispose() }
    }
}

# ============================================================
# URL Test helpers
# ============================================================

function Wait-ForPort {
    param($Port, $MaxWait = 15)
    $waited = 0
    while ($waited -lt $MaxWait) {
        $tcp = $null
        try {
            $tcp = New-Object System.Net.Sockets.TcpClient
            $ar = $tcp.BeginConnect("127.0.0.1", $Port, $null, $null)
            if ($ar.AsyncWaitHandle.WaitOne(500)) {
                $tcp.EndConnect($ar)
                $tcp.Close()
                return $true
            }
        }
        catch {
            # Port not ready yet
        }
        finally {
            if ($tcp) { $tcp.Dispose() }
        }
        Start-Sleep -Milliseconds 500
        $waited = $waited + 1
    }
    return $false
}

function Invoke-ProcessTreeCleanup {
    param($PidFile, $Tag, $ConfigPath)

    # Layer 1: kill process tree by PID file
    if (Test-Path $PidFile) {
        $pidContent = Get-Content $PidFile -Raw
        $procId = 0
        if ([int]::TryParse($pidContent, [ref]$procId)) {
            try {
                $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
                if ($proc) {
                    # taskkill /T = kill process tree (parent + all children)
                    taskkill /F /T /PID $procId >$null 2>$null
                    Start-Sleep -Milliseconds 300
                }
            }
            catch { }
        }
    }

    # Layer 2: pattern kill by tag
    try {
        $allProcs = Get-WmiObject Win32_Process
        foreach ($p in $allProcs) {
            $cmdLine = $p.CommandLine
            if ($cmdLine -and ($cmdLine -match [regex]::Escape($Tag))) {
                # Skip this script itself
                if ($cmdLine -notmatch 'test\.ps1') {
                    taskkill /F /PID $p.ProcessId >$null 2>$null
                }
            }
        }
    }
    catch { }

    # Layer 3: pattern kill by config filename
    $configFile = Split-Path $ConfigPath -Leaf
    if ($configFile) {
        try {
            $allProcs = Get-WmiObject Win32_Process
            foreach ($p in $allProcs) {
                $cmdLine = $p.CommandLine
                if ($cmdLine -and ($cmdLine -match [regex]::Escape($configFile))) {
                    if ($cmdLine -notmatch 'test\.ps1') {
                        taskkill /F /PID $p.ProcessId >$null 2>$null
                    }
                }
            }
        }
        catch { }
    }

    # Cleanup files
    Remove-Item -Force $PidFile -ErrorAction SilentlyContinue
    Remove-Item -Force $ConfigPath -ErrorAction SilentlyContinue
}

# ============================================================
# URL Test
# ============================================================

function Invoke-UrlTest {
    # Validate config path
    if (-not (Test-Path $ConfigPath)) {
        Write-JsonResult @{ success = $false; error = "config file not found: $ConfigPath" }
        exit 0
    }

    # Resolve bin path (relative paths are relative to project root = scripts/..)
    $scriptDir = $PSScriptRoot
    $projectDir = Split-Path $scriptDir -Parent
    $resolvedBinPath = $BinPath
    if (-not [System.IO.Path]::IsPathRooted($BinPath)) {
        $resolvedBinPath = Join-Path $projectDir $BinPath
    }
    # On Windows, try appending .exe if not present
    if (-not (Test-Path $resolvedBinPath) -and -not $resolvedBinPath.EndsWith('.exe')) {
        $resolvedBinPath = $resolvedBinPath + '.exe'
    }
    if (-not (Test-Path $resolvedBinPath)) {
        Write-JsonResult @{ success = $false; error = "binary not found: $resolvedBinPath" }
        exit 0
    }

    $pidFile = "$ConfigPath.pid"

    # Build run arguments per bin type
    $runArgs = @()
    switch ($BinType) {
        'xray'     { $runArgs = @('run', '-config', $ConfigPath) }
        'sslocal'  { $runArgs = @('-c', $ConfigPath) }
        'sing-box' { $runArgs = @('run', '-c', $ConfigPath) }
        default {
            Write-JsonResult @{ success = $false; error = "unknown bin_type: $BinType" }
            exit 0
        }
    }

    # Add bin directory to PATH (sslocal needs to find obfs-local.exe)
    $binDir = Split-Path $resolvedBinPath -Parent
    $oldPath = $env:PATH
    $env:PATH = "$binDir;$oldPath"

    # Start proxy process
    try {
        $procInfo = New-Object System.Diagnostics.ProcessStartInfo
        $procInfo.FileName = $resolvedBinPath
        $procInfo.Arguments = $runArgs -join ' '
        $procInfo.UseShellExecute = $false
        $procInfo.CreateNoWindow = $true
        $procInfo.RedirectStandardOutput = $true
        $procInfo.RedirectStandardError = $true
        $procInfo.WorkingDirectory = $projectDir

        $process = [System.Diagnostics.Process]::Start($procInfo)
        $process.Id | Out-File -FilePath $pidFile -Encoding ASCII
    }
    catch {
        $env:PATH = $oldPath
        Write-JsonResult @{ success = $false; error = "failed to start proxy: $($_.Exception.Message)" }
        exit 0
    }

    # Wait for port
    if (-not (Wait-ForPort $LocalPort 15)) {
        Invoke-ProcessTreeCleanup $pidFile $Tag $ConfigPath
        $env:PATH = $oldPath
        Write-JsonResult @{ success = $false; error = "proxy did not start listening on port $LocalPort within 15s" }
        exit 0
    }

    # Check curl.exe availability
    $curlBin = $null
    $knownPaths = @(
        "C:\Windows\System32\curl.exe",
        "curl.exe"
    )
    foreach ($cp in $knownPaths) {
        try {
            if (Get-Command $cp -ErrorAction SilentlyContinue) {
                $curlBin = $cp
                break
            }
        }
        catch { }
    }
    if (-not $curlBin) {
        Invoke-ProcessTreeCleanup $pidFile $Tag $ConfigPath
        $env:PATH = $oldPath
        Write-JsonResult @{ success = $false; error = "curl.exe not found" }
        exit 0
    }

    # Run curl through SOCKS5 proxy with timing
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $httpCode = "000"
    try {
        $curlResult = & $curlBin -o NUL -s -w "%{http_code}" `
            --connect-timeout 3 --max-time $CurlTimeout `
            --socks5-hostname "127.0.0.1:$LocalPort" `
            "$TestUrl" 2>$null
        if ($LASTEXITCODE -eq 0 -and $curlResult) {
            $httpCode = $curlResult.Trim()
        }
    }
    catch {
        $httpCode = "000"
    }
    $sw.Stop()

    # Cleanup
    Invoke-ProcessTreeCleanup $pidFile $Tag $ConfigPath
    $env:PATH = $oldPath

    # Output result
    if ($httpCode -match '^(200|204|301|302|307|308)$') {
        Write-JsonResult @{ success = $true; http_code = [int]$httpCode; latency_ms = $sw.ElapsedMilliseconds }
    }
    else {
        Write-JsonResult @{ success = $false; error = "HTTP $httpCode"; http_code = [int]$httpCode; latency_ms = $sw.ElapsedMilliseconds }
    }
}

# ============================================================
# Dispatch
# ============================================================

switch ($Action) {
    'tcp_ping' { Invoke-TcpPing $Address $Port $Timeout $Tag }
    'url_test' { Invoke-UrlTest }
    default    { Write-JsonResult @{ success = $false; error = "unknown action: $Action" }; exit 0 }
}
