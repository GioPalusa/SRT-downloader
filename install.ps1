$ErrorActionPreference = 'Stop'

# Force TLS 1.2 for Windows PowerShell 5.1, which defaults to TLS 1.0/1.1
# on older Windows builds and would otherwise fail against github.com.
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch {
    # Ignore on platforms where SecurityProtocol is not settable (e.g. PS 7+).
}

$repo = if ($env:SRT_DOWNLOADER_REPO) {
    $env:SRT_DOWNLOADER_REPO
} else {
    'GioPalusa/SRT-downloader'
}

$installDir = if ($env:SRT_DOWNLOADER_INSTALL_DIR) {
    $env:SRT_DOWNLOADER_INSTALL_DIR
} else {
    Join-Path $env:LOCALAPPDATA 'Programs\SRT Downloader'
}

$version = if ($env:SRT_DOWNLOADER_VERSION) {
    $env:SRT_DOWNLOADER_VERSION
} else {
    'latest'
}

$normalizedInstallDir = [System.IO.Path]::GetFullPath($installDir)
$targetPath = Join-Path $normalizedInstallDir 'srt-download.exe'

if ($version -eq 'latest') {
    $downloadUrl = "https://github.com/$repo/releases/latest/download/srt-download-windows-x64.exe"
} else {
    $tag = if ($version.StartsWith('v')) { $version } else { "v$version" }
    $downloadUrl = "https://github.com/$repo/releases/download/$tag/srt-download-windows-x64.exe"
}

New-Item -ItemType Directory -Path $normalizedInstallDir -Force | Out-Null

Write-Host "Downloading $downloadUrl"
Invoke-WebRequest -Uri $downloadUrl -OutFile $targetPath -UseBasicParsing

# Clear Mark-of-the-Web so SmartScreen does not block the first run.
try {
    Unblock-File -Path $targetPath -ErrorAction Stop
} catch {
    # Unblock-File may not exist on minimal Windows installs; ignore.
}

$currentUserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$pathEntries = @()
if (-not [string]::IsNullOrWhiteSpace($currentUserPath)) {
    $pathEntries = $currentUserPath.Split(';', [System.StringSplitOptions]::RemoveEmptyEntries)
}

$alreadyPresent = $false
foreach ($entry in $pathEntries) {
    if ($entry.TrimEnd('\').TrimEnd('/') -ieq $normalizedInstallDir.TrimEnd('\').TrimEnd('/')) {
        $alreadyPresent = $true
        break
    }
}

$pathWasModified = $false
if (-not $alreadyPresent) {
    $newEntries = @($pathEntries + $normalizedInstallDir | Select-Object -Unique)
    $newUserPath = $newEntries -join ';'
    [Environment]::SetEnvironmentVariable('Path', $newUserPath, 'User')
    $env:Path = "$normalizedInstallDir;$env:Path"
    $pathWasModified = $true
}

Write-Host ""
Write-Host "Installed srt-download.exe to $targetPath"

if ($pathWasModified) {
    Write-Host ""
    Write-Host "Added $normalizedInstallDir to the user PATH."
    Write-Host "Open a new terminal so the updated PATH takes effect."
}

Write-Host ""
Write-Host "Quick start:"
Write-Host "  srt-download                  scan current folder"
Write-Host "  srt-download -l sv            primary language (English added as fallback)"
Write-Host "  srt-download --list-providers show provider order"
Write-Host "  srt-download --help           full help"
Write-Host ""
Write-Host "Drop a srt-downloader.yaml next to your videos for defaults and provider creds."
Write-Host "Docs: https://github.com/$repo#readme"
