$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$OutputEncoding = [Console]::OutputEncoding
$selectedPython = $null
$launcherArgs = @()
$probe = "import sys,struct;sys.exit(0 if sys.version_info[:2]==(3,12) and struct.calcsize('P')==8 else 1)"
$pythonCommand = Get-Command py -ErrorAction SilentlyContinue
if ($pythonCommand) {
    try {
        & $pythonCommand.Source -3.12 -c $probe 2>$null
        if ($LASTEXITCODE -eq 0) { $selectedPython = $pythonCommand.Source; $launcherArgs = @('-3.12') }
    } catch { }
}
if (-not $selectedPython) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        try {
            & $pythonCommand.Source -c $probe 2>$null
            if ($LASTEXITCODE -eq 0) { $selectedPython = $pythonCommand.Source }
        } catch { }
    }
}
if (-not $selectedPython) { throw 'Install Python 3.12 (64-bit), then rerun setup.' }
& $selectedPython @launcherArgs (Join-Path $PSScriptRoot 'setup_tools.py') @args
if ($LASTEXITCODE -ne 0) { throw 'Setup did not complete. See the message above.' }
