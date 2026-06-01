$ErrorActionPreference = 'Stop'

$installDir = if ($env:SRT_DOWNLOADER_INSTALL_DIR) {
    $env:SRT_DOWNLOADER_INSTALL_DIR
} else {
    Join-Path $env:LOCALAPPDATA 'Programs\SRT Downloader'
}

$normalizedInstallDir = [System.IO.Path]::GetFullPath($installDir)
$targetPath = Join-Path $normalizedInstallDir 'srt-download.exe'

if (Test-Path $targetPath) {
    Remove-Item -LiteralPath $targetPath -Force
    Write-Host "Removed $targetPath"
} else {
    Write-Host "No binary found at $targetPath"
}

# Remove the install directory if it is now empty.
if ((Test-Path $normalizedInstallDir) -and -not (Get-ChildItem -LiteralPath $normalizedInstallDir -Force)) {
    Remove-Item -LiteralPath $normalizedInstallDir -Force
    Write-Host "Removed empty directory $normalizedInstallDir"
}

# Strip the install directory from the user PATH.
$currentUserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not [string]::IsNullOrWhiteSpace($currentUserPath)) {
    $entries = $currentUserPath.Split(';', [System.StringSplitOptions]::RemoveEmptyEntries)
    $filtered = @($entries | Where-Object {
        $_.TrimEnd('\').TrimEnd('/') -ine $normalizedInstallDir.TrimEnd('\').TrimEnd('/')
    })
    if ($filtered.Count -ne $entries.Count) {
        $newUserPath = $filtered -join ';'
        [Environment]::SetEnvironmentVariable('Path', $newUserPath, 'User')
        Write-Host "Removed $normalizedInstallDir from the user PATH."
    }
}

Write-Host 'srt-download uninstalled.'
