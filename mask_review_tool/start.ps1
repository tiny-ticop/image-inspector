$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$OutputEncoding = [Console]::OutputEncoding
$pythonPath = Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Missing LH-analysis/.venv. Follow the environment setup steps in mask_review_tool/README.md.'
}
& $pythonPath (Join-Path $PSScriptRoot 'scripts\server.py') @args
