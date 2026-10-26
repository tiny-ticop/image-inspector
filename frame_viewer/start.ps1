$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$OutputEncoding = [Console]::OutputEncoding
$pythonPath = Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Missing LH-analysis/.venv. See frame_viewer/README.md.'
}
& $pythonPath (Join-Path $PSScriptRoot 'server.py') @args
exit $LASTEXITCODE
