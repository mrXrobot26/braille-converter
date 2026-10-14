# Build the Windows program into dist\NassBraille\ (one folder, no Python needed).
# usage: powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

& $py -m pytest tests -q -x
if ($LASTEXITCODE -ne 0) { throw "tests failed - not building" }

$iconArgs = @()
if (Test-Path "assets\icon.ico") { $iconArgs = @("--icon", "assets\icon.ico", "--add-data", "assets;assets") }

& $py -m PyInstaller --noconfirm --clean --windowed `
    --name NassBraille `
    --collect-all pymupdf `
    --collect-data docx `
    @iconArgs `
    app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$zip = "dist\NassBraille.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "dist\NassBraille\*" -DestinationPath $zip
Write-Host "built: dist\NassBraille\NassBraille.exe and $zip"
