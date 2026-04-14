$ErrorActionPreference = 'Stop'

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

$normalizedInstallDir = [System.IO.Path]::GetFullPath($installDir)
$targetPath = Join-Path $normalizedInstallDir 'srt-download.exe'
$downloadUrl = "https://github.com/$repo/releases/latest/download/srt-download-windows-x64.exe"

New-Item -ItemType Directory -Path $normalizedInstallDir -Force | Out-Null
Invoke-WebRequest -Uri $downloadUrl -OutFile $targetPath

$currentUserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$pathEntries = @()
if (-not [string]::IsNullOrWhiteSpace($currentUserPath)) {
    $pathEntries = $currentUserPath.Split(';', [System.StringSplitOptions]::RemoveEmptyEntries)
}

$alreadyPresent = $false
foreach ($entry in $pathEntries) {
    if ($entry.TrimEnd('\\') -ieq $normalizedInstallDir.TrimEnd('\\')) {
        $alreadyPresent = $true
        break
    }
}

if (-not $alreadyPresent) {
    $newEntries = @($pathEntries + $normalizedInstallDir | Select-Object -Unique)
    $newUserPath = $newEntries -join ';'
    [Environment]::SetEnvironmentVariable('Path', $newUserPath, 'User')
    $env:Path = "$normalizedInstallDir;$env:Path"
    Write-Host "Added $normalizedInstallDir to the user PATH."
}

Write-Host "Installed srt-download.exe to $targetPath"
Write-Host 'Open a new terminal, then run: srt-download --help'
