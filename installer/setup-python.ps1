# setup-python.ps1
# Downloads and prepares the Python 3.12.10 embeddable package for bundling
# with the OBS Open Golf Coach plugin installer.
#
# Usage: powershell -ExecutionPolicy Bypass -File setup-python.ps1 [-OutputDir build/python-embed]

param(
    [string]$OutputDir = "build/python-embed"
)

$ErrorActionPreference = "Stop"

$PythonVersion = "3.12.10"
$PythonZipUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$GetPipUrl = "https://bootstrap.pypa.io/get-pip.py"
$PthFile = "python312._pth"

Write-Host "=== Open Golf Coach: Python Embed Setup ===" -ForegroundColor Cyan
Write-Host "Python version: $PythonVersion"
Write-Host "Output directory: $OutputDir"

# Create output directory
if (Test-Path $OutputDir) {
    Remove-Item -Recurse -Force $OutputDir
}
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

# Download Python embeddable zip
$zipPath = "$OutputDir/python-embed.zip"
Write-Host "`nDownloading Python $PythonVersion embeddable package..." -ForegroundColor Yellow
Invoke-WebRequest -Uri $PythonZipUrl -OutFile $zipPath -UseBasicParsing
Write-Host "Downloaded: $zipPath"

# Extract
Write-Host "Extracting..." -ForegroundColor Yellow
Expand-Archive -Path $zipPath -DestinationPath $OutputDir -Force
Remove-Item $zipPath
Write-Host "Extracted to $OutputDir"

# Enable import site in ._pth file (required for pip and site-packages)
$pthPath = Join-Path $OutputDir $PthFile
if (Test-Path $pthPath) {
    Write-Host "`nEnabling import site in $PthFile..." -ForegroundColor Yellow
    $content = Get-Content $pthPath -Raw
    $content = $content -replace '#import site', 'import site'
    Set-Content -Path $pthPath -Value $content -NoNewline
    Write-Host "import site enabled"
} else {
    Write-Error "$PthFile not found at $pthPath"
    exit 1
}

# Bootstrap pip
$pythonExe = Join-Path $OutputDir "python.exe"
$getPipPath = "$OutputDir/get-pip.py"

Write-Host "`nDownloading get-pip.py..." -ForegroundColor Yellow
Invoke-WebRequest -Uri $GetPipUrl -OutFile $getPipPath -UseBasicParsing

Write-Host "Installing pip..." -ForegroundColor Yellow
& $pythonExe $getPipPath --no-warn-script-location
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to install pip"
    exit 1
}
Remove-Item $getPipPath
Write-Host "pip installed"

# Install opengolfcoach
Write-Host "`nInstalling opengolfcoach..." -ForegroundColor Yellow
& $pythonExe -m pip install opengolfcoach --no-warn-script-location
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to install opengolfcoach"
    exit 1
}
Write-Host "opengolfcoach installed"

# Create scripts subdirectory for the plugin
$scriptsDir = Join-Path $OutputDir "scripts"
New-Item -ItemType Directory -Force -Path $scriptsDir | Out-Null

Write-Host "`n=== Setup complete ===" -ForegroundColor Green
Write-Host "Python embed ready at: $OutputDir"
