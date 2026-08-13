<#
.SYNOPSIS
    Launch the built Windows EXE and prove it actually serves.

.DESCRIPTION
    The release job used to check only that a file appeared on disk. That cannot
    catch the two ways this build really fails:

      1. The EXE dies on launch. A missing hidden import is invisible to
         PyInstaller's static analysis — v2.16.7 shipped `import resource`
         (Unix-only) and was caught by luck, because a test happened to import
         the module. Nothing else would have noticed.

      2. The EXE comes up without its frontend. app_factory only *warns* when the
         static bundle is absent and starts anyway, so an EXE with no UI in it
         passes every existence check and every backend health probe.

    So this launches the real binary, waits for it to serve, and then demands the
    frontend it is supposed to carry — including one asset fetched through the
    /assets mount, which is what proves the bundle is really inside.

.PARAMETER ExePath
    Path to the built executable.

.PARAMETER Port
    Port to run the smoke instance on. Kept off the app's 8888 default so a
    developer running this locally does not collide with a real instance.

.PARAMETER TimeoutSeconds
    How long to wait for the server to answer before calling the build broken.
#>
param(
    [Parameter(Mandatory = $true)][string]$ExePath,
    [int]$Port = 8899,
    [int]$TimeoutSeconds = 120
)

$ErrorActionPreference = "Stop"

$exe = Get-Item -LiteralPath $ExePath
$workDir = $exe.Directory.FullName
$stdout = Join-Path $workDir "smoke-stdout.log"
$stderr = Join-Path $workDir "smoke-stderr.log"
$baseUrl = "http://127.0.0.1:$Port"

function Show-AppOutput {
    foreach ($log in @($stdout, $stderr)) {
        if (Test-Path $log) {
            Write-Host "----- $(Split-Path $log -Leaf) -----"
            Get-Content $log -Tail 60 | ForEach-Object { Write-Host $_ }
        }
    }
}

# OC_PORT moves it off the default. DOCKER_CONTAINER is the app's existing
# switch for "do not open a browser" — the name is a misnomer here, but adding a
# second switch for the same behavior would be worse.
$env:OC_PORT = "$Port"
$env:DOCKER_CONTAINER = "1"

Write-Host "Launching $($exe.Name) on port $Port ..."
$proc = Start-Process -FilePath $exe.FullName -WorkingDirectory $workDir `
    -PassThru -NoNewWindow -RedirectStandardOutput $stdout -RedirectStandardError $stderr

try {
    # --- 1. Does it serve at all? -------------------------------------------
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $isServing = $false
    while ((Get-Date) -lt $deadline) {
        if ($proc.HasExited) {
            Show-AppOutput
            throw "The EXE exited during startup with code $($proc.ExitCode)."
        }
        try {
            $status = Invoke-WebRequest -Uri "$baseUrl/api/auth/status" -UseBasicParsing -TimeoutSec 5
            if ($status.StatusCode -eq 200) { $isServing = $true; break }
        }
        catch {
            Start-Sleep -Seconds 2
        }
    }
    if (-not $isServing) {
        Show-AppOutput
        throw "No answer from $baseUrl/api/auth/status within $TimeoutSeconds seconds."
    }
    Write-Host "OK  backend answered /api/auth/status"

    # --- 2. Is the frontend actually inside? --------------------------------
    $index = Invoke-WebRequest -Uri "$baseUrl/" -UseBasicParsing -TimeoutSec 15
    if ($index.Content -notmatch "<title>OC Proxy Downloader</title>") {
        Show-AppOutput
        throw "The root path did not return the app's index.html — the frontend bundle is missing."
    }
    Write-Host "OK  index.html served"

    # --- 3. Does the /assets mount reach a real bundled file? ---------------
    # A built index always references its hashed JS bundle. Fetching the one it
    # names is what distinguishes "index.html got bundled" from "the whole dist
    # directory got bundled".
    $assetMatch = [regex]::Match($index.Content, '/assets/[A-Za-z0-9._-]+\.js')
    if (-not $assetMatch.Success) {
        Show-AppOutput
        throw "index.html references no /assets/*.js bundle — the frontend build is not what shipped."
    }
    $assetPath = $assetMatch.Value
    $asset = Invoke-WebRequest -Uri "$baseUrl$assetPath" -UseBasicParsing -TimeoutSec 15
    if ($asset.StatusCode -ne 200 -or $asset.RawContentLength -le 0) {
        Show-AppOutput
        throw "$assetPath did not serve — the /assets mount is empty."
    }
    Write-Host "OK  $assetPath served ($($asset.RawContentLength) bytes)"

    Write-Host "Smoke test passed."
}
finally {
    if (-not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        $proc.WaitForExit(15000) | Out-Null
    }
}
