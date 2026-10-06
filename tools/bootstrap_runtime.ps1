# Used only when start.bat cannot find Python; no system settings are changed.
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$offline = $false
$approved = $false
$archive = $null
for ($index = 0; $index -lt $args.Count; $index++) {
    if ($args[$index] -eq '--cli') { break }
    if ($args[$index] -eq '--offline') { $offline = $true }
    if ($args[$index] -in @('--yes', '--setup-online')) { $approved = $true }
    if ($args[$index] -eq '--runtime-archive') {
        $index++
        if ($index -ge $args.Count) { throw 'Missing runtime archive argument.' }
        $archive = [IO.Path]::GetFullPath($args[$index])
    }
}
$stage = $null
$phase = 'preparation'
try {
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'Windows 64-bit is required.' }
    $tag = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') { 'windows-arm64' } else { 'windows-x86_64' }
    $catalog = Get-Content -LiteralPath (Join-Path $projectRoot 'dependencies/python-sources.json') -Raw | ConvertFrom-Json
    $pin = $catalog.platforms.$tag
    $runtimeRoot = if ($env:VIDEOMATE_RUNTIME_ROOT) { [IO.Path]::GetFullPath($env:VIDEOMATE_RUNTIME_ROOT) } else { Join-Path $projectRoot 'dependencies/python' }
    $cache = Join-Path $projectRoot 'dependencies/cache'
    [IO.Directory]::CreateDirectory($runtimeRoot) | Out-Null
    [IO.Directory]::CreateDirectory($cache) | Out-Null
    $stage = Join-Path $runtimeRoot ('.bootstrap-' + [Guid]::NewGuid().ToString('N'))
    [IO.Directory]::CreateDirectory($stage) | Out-Null
    if (-not $archive) {
        $archive = Join-Path $cache $pin.filename
        if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
            if ($offline) { throw 'Offline setup needs a pinned Python/Tk archive.' }
            if (-not $approved) {
                Write-Output 'A compatible Python was not found. VideoMate can download its pinned Python/Tk runtime into the software folder.'
                Write-Output 'No administrator access, PATH changes, venv or Conda installation is needed.'
                Write-Output 'Alternatively install Python 3.11+ from https://www.python.org/downloads/ or set VIDEOMATE_PYTHON to an existing interpreter.'
                if ([Console]::IsInputRedirected) {
                    Write-Output 'No interactive terminal is available. Run start.bat --yes to approve setup, or use the complete desktop download.'
                    exit 2
                }
                $answer = Read-Host 'Download and install the local Python/Tk runtime? [y/N]'
                if ($answer -notmatch '^(?i:y|yes)$') {
                    Write-Output 'Setup cancelled. No software was downloaded.'
                    exit 2
                }
            }
            Write-Output 'Downloading pinned Python/Tk. No system packages will change.'
            $archive = Join-Path $stage 'runtime.tar.gz'
            & curl.exe --fail --location --proto '=https' --proto-redir '=https' --connect-timeout 30 --max-time 600 --max-filesize 268435456 --retry 2 --output $archive $pin.url
            if ($LASTEXITCODE -ne 0) { throw 'Python download failed.' }
        }
    }
    $phase = 'checksum verification'
    $stream = [IO.File]::OpenRead($archive)
    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        if ($stream.Length -gt 268435456) { throw 'Python archive exceeds size limit.' }
        $actual = [BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-', '').ToLowerInvariant()
    } finally {
        $stream.Dispose()
        $hasher.Dispose()
    }
    if ($actual -ne $pin.sha256) {
        throw 'Python archive checksum mismatch.'
    }
    # Only the exact pinned upstream archive can reach this extraction step.
    $unpack = Join-Path $stage 'unpack'
    [IO.Directory]::CreateDirectory($unpack) | Out-Null
    $phase = 'archive extraction'
    # Windows tar versions may encode non-ASCII arguments through the active
    # codepage. Use ASCII relative arguments under a Unicode-safe working dir.
    [IO.File]::Copy($archive, (Join-Path $stage 'pinned.tar.gz'))
    Push-Location -LiteralPath $stage
    try {
        & tar.exe -xzf pinned.tar.gz -C unpack
        if ($LASTEXITCODE -ne 0) { throw 'Python archive extraction failed.' }
    } finally { Pop-Location }
    $phase = 'runtime installation'
    & (Join-Path $unpack 'python/python.exe') -I -X utf8 (Join-Path $projectRoot 'tools/install_python.py') --platform $tag --archive $archive
    if ($LASTEXITCODE -ne 0) { throw 'Python runtime installation failed.' }
} catch {
    Write-Output "Python setup failed during $phase. Supply an approved Python using VIDEOMATE_PYTHON, or see docs/launchers.md. Existing software was preserved."
    exit 2
} finally {
    if ($stage) {
        $resolvedStage = [IO.Path]::GetFullPath($stage)
        $allowedRoot = [IO.Path]::GetFullPath($runtimeRoot).TrimEnd('\') + '\'
        if (-not $resolvedStage.StartsWith($allowedRoot, [StringComparison]::OrdinalIgnoreCase) -or -not ([IO.Path]::GetFileName($resolvedStage)).StartsWith('.bootstrap-')) {
            throw 'Refusing cleanup outside the owned staging directory.'
        }
        Remove-Item -LiteralPath $resolvedStage -Recurse -Force
    }
}
