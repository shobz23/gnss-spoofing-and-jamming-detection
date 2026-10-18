param([int]$Port = 8765, [switch]$Demo)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
$PythonPath = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $PythonPath)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed.' }
    & $PythonPath -m pip install -e '.[dev]'
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
if ($Demo) {
    & $PythonPath -m gnss_sentinel.cli demo
    if ($LASTEXITCODE -ne 0) { throw 'Demo preparation failed.' }
}
Write-Host "GNSS Sentinel: http://127.0.0.1:$Port"
& $PythonPath -m gnss_sentinel.cli serve --port $Port
