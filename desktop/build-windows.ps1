$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
Set-Location $root
$python = if ($env:PYTHON) { $env:PYTHON } else { "python" }
& $python -m PyInstaller --noconfirm --clean desktop/payroll.spec
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
